package main

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"time"
)

// The separate queue starts after both cloud shares are durably recorded.
// It never re-downloads files that the transfer worker already cleaned.
func (m *marketplaceManager) loop() {
	defer close(m.done)
	if m.app.credentialsReady != nil {
		select {
		case <-m.app.credentialsReady:
		case <-m.app.ctx.Done():
			return
		}
	}
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	m.notify()
	for {
		select {
		case <-m.app.ctx.Done():
			return
		case <-ticker.C:
		case <-m.wake:
		}
		if !m.opMu.TryLock() {
			continue
		}
		m.mu.Lock()
		enabled := m.state.Config.Enabled && m.api != nil && m.storeError == ""
		m.mu.Unlock()
		if !enabled {
			m.opMu.Unlock()
			continue
		}
		if _, err := m.collect(); err != nil {
			m.opMu.Unlock()
			continue
		}
		m.mu.Lock()
		id := ""
		for _, j := range m.state.Jobs {
			if j.Status == "published" || j.Status == "attention" {
				continue
			}
			if next, e := time.Parse(time.RFC3339, j.NextRunAt); e == nil && next.After(m.now()) {
				continue
			}
			id = j.ID
			break
		}
		ctx, cancel := context.WithTimeout(m.app.ctx, 2*time.Minute)
		if id != "" {
			m.activeID, m.activeStop = id, cancel
		}
		m.mu.Unlock()
		if id != "" {
			_ = m.step(ctx, id)
		}
		cancel()
		m.mu.Lock()
		m.activeID, m.activeStop = "", nil
		m.mu.Unlock()
		m.opMu.Unlock()
		if id != "" {
			m.notify()
		}
	}
}

func (m *marketplaceManager) deferJob(id, status, message string, delay time.Duration) error {
	return m.change(id, func(j *MarketplaceJob) {
		j.Status, j.Error = status, message
		j.NextRunAt = ""
		if delay > 0 {
			j.NextRunAt = m.now().Add(delay).UTC().Format(time.RFC3339)
		}
	})
}

func (m *marketplaceManager) readFailure(id string, err error) error {
	j, _ := m.job(id)
	delay := time.Minute * time.Duration(1<<min(j.Attempts, 6))
	status := j.Status
	if j.Attempts >= 7 {
		status = "attention"
		delay = 0
	}
	return m.change(id, func(j *MarketplaceJob) {
		j.Status, j.Error = status, err.Error()
		j.Attempts++
		j.NextRunAt = ""
		if delay > 0 {
			j.NextRunAt = m.now().Add(delay).UTC().Format(time.RFC3339)
		}
	})
}

func (m *marketplaceManager) step(ctx context.Context, id string) error {
	j, ok := m.job(id)
	if !ok {
		return errors.New("铺货任务不存在")
	}
	m.mu.Lock()
	api := m.api
	fingerprint := marketplaceFingerprint(m.creds)
	enabled := m.state.Config.Enabled
	m.mu.Unlock()
	if !enabled || api == nil {
		return nil
	}
	if j.AccountFingerprint != fingerprint {
		return m.deferJob(id, "attention", "当前闲管家应用与任务创建时不同，请连接原应用后核对结果", 0)
	}
	switch j.Status {
	case "published", "attention":
		return nil
	case "waiting_materials":
		return m.prepareMaterials(ctx, j)
	case "creating", "create_unknown":
		return m.reconcileCreate(ctx, api, j)
	case "publishing", "confirming", "created":
		return m.confirmOrPublish(ctx, api, j)
	case "queued":
	default:
		return nil
	}
	t, ok := m.app.transfers.job(j.TransferID)
	if !ok {
		return m.deferJob(id, "attention", "原下载任务已不存在，无法核对待发布资料", 0)
	}
	if err := marketplaceTransferReady(t); err != nil {
		return m.deferJob(id, "waiting_materials", err.Error(), 5*time.Minute)
	}
	if t.BundleSHA256 != j.BundleSHA256 {
		return m.deferJob(id, "attention", "分享包已变化，保留现有任务供核对", 0)
	}
	if err := m.checkShop(ctx, api, j.ShopUserName); err != nil {
		return m.readFailure(id, err)
	}
	if len(j.Payload) == 0 || !json.Valid(j.Payload) {
		return m.deferJob(id, "attention", "待发布商品资料缺失，请核对任务", 0)
	}
	if j.CreateIssuedAt != "" {
		return m.deferJob(id, "create_unknown", "此前创建请求尚待核对，不会重复提交", time.Second)
	}
	if err := m.change(id, func(j *MarketplaceJob) {
		j.Status = "creating"
		j.CreateIssuedAt = m.nowString()
		j.Error = ""
		j.NextRunAt = ""
		j.Attempts++
	}); err != nil {
		return err
	}
	var created struct {
		ProductID     int64 `json:"product_id"`
		ProductStatus int   `json:"product_status"`
	}
	err := api.call(ctx, "/api/open/product/create", j.Payload, &created)
	if err != nil {
		var e *xgjError
		if errors.As(err, &e) && !e.Ambiguous {
			return m.change(id, func(j *MarketplaceJob) { j.Status, j.Error = "attention", err.Error(); j.CreateIssuedAt = "" })
		}
		return m.deferJob(id, "create_unknown", "创建请求结果尚未确认，稍后按商家编码核对；不会重复创建", time.Minute)
	}
	if created.ProductID <= 0 {
		return m.deferJob(id, "create_unknown", "创建接口未返回有效商品编号，正在核对远端结果", time.Minute)
	}
	return m.change(id, func(j *MarketplaceJob) {
		j.ProductID = strconv.FormatInt(created.ProductID, 10)
		j.Status = "created"
		j.Error = ""
		j.Attempts = 0
	})
}

func (m *marketplaceManager) prepareMaterials(ctx context.Context, j MarketplaceJob) error {
	t, ok := m.app.transfers.job(j.TransferID)
	if !ok {
		return m.deferJob(j.ID, "attention", "原下载任务已不存在", 0)
	}
	if err := marketplaceTransferReady(t); err != nil {
		return m.deferJob(j.ID, "waiting_materials", err.Error(), 5*time.Minute)
	}
	if t.BundleSHA256 != j.BundleSHA256 {
		return m.deferJob(j.ID, "attention", "任务对应分享包已变化，请核对版本", 0)
	}
	if item, ok := m.app.lib.snapshot().Descriptions[strings.ToLower(t.Repo)]; ok && readyGameDetails(item) && item.PosterURL != "" {
		applyTransferDetails(&t, item)
	}
	payload, title, content, err := marketplacePayload(t, j.Config, j.OuterID)
	if err != nil {
		if marketplaceMaterialsReady(t) {
			return m.deferJob(j.ID, "attention", err.Error(), 0)
		}
		return m.refreshMaterials(ctx, j, t)
	}
	return m.change(j.ID, func(j *MarketplaceJob) {
		j.Payload = payload
		j.Title, j.Content, j.PosterURL = title, content, t.PosterURL
		j.Baidu, j.Quark = t.Outputs["baidu"].Share, t.Outputs["quark"].Share
		j.Status, j.Error, j.NextRunAt = "queued", "", ""
		j.Attempts = 0
	})
}

func (m *marketplaceManager) refreshMaterials(ctx context.Context, j MarketplaceJob, t TransferJob) error {
	result, err := m.app.aigc.get(ctx, []string{t.Repo})
	if err != nil {
		return m.readFailure(j.ID, err)
	}
	var item Description
	if len(result.Items) > 0 {
		item = result.Items[0]
	}
	if readyGameDetails(item) && item.PosterURL != "" {
		copy := cloneTransfer(t)
		applyTransferDetails(&copy, item)
		if _, _, _, err := marketplacePayload(copy, j.Config, j.OuterID); err == nil {
			if err = m.app.lib.saveDescriptions([]Description{item}); err != nil {
				return m.readFailure(j.ID, errors.New("保存中文资料失败"))
			}
			if err = m.app.transfers.modify(t.ID, func(t *TransferJob) { applyTransferDetails(t, item) }, true); err != nil {
				return err
			}
			return m.deferJob(j.ID, "waiting_materials", "资料已补齐，准备生成商品", time.Second)
		}
	}
	if item.Status == "pending" {
		return m.deferJob(j.ID, "waiting_materials", "中文资料或图片正在生成，完成后继续铺货", 30*time.Second)
	}
	if !m.app.aigc.hasToken() {
		return m.deferJob(j.ID, "waiting_materials", "请配置 AIGCNEWS Token，补全中文简介和图片后自动继续", 5*time.Minute)
	}
	wait := max(item.RetryAfter, item.PosterRetryAfter)
	if wait > 0 {
		return m.deferJob(j.ID, "waiting_materials", "等待中文资料服务允许重试", time.Duration(min(wait, 3600))*time.Second)
	}
	if j.MetadataAttempts >= 3 {
		return m.deferJob(j.ID, "attention", "三次资料补全后仍缺少可用图片或简介，请在目录补全后重试铺货", 0)
	}
	if err = m.change(j.ID, func(j *MarketplaceJob) {
		j.MetadataAttempts++
		j.NextRunAt = m.now().Add(5 * time.Minute).UTC().Format(time.RFC3339)
	}); err != nil {
		return err
	}
	_, _, err = m.app.aigc.generate(ctx, t.Repo)
	if err != nil {
		return m.readFailure(j.ID, err)
	}
	return m.deferJob(j.ID, "waiting_materials", "已提交资料补全，正在等待结果", 30*time.Second)
}

type marketplaceProduct struct {
	ProductID     int64  `json:"product_id"`
	ProductStatus int    `json:"product_status"`
	PublishStatus *int   `json:"publish_status"`
	OuterID       string `json:"outer_id"`
	PublishShop   []struct {
		UserName string `json:"user_name"`
		Status   *int   `json:"status"`
		ItemID   int64  `json:"item_id"`
	} `json:"publish_shop"`
}

func marketplacePublished(p marketplaceProduct, user string) (int64, bool) {
	if p.ProductStatus != 22 || p.PublishStatus == nil || *p.PublishStatus != 3 {
		return 0, false
	}
	count := 0
	var item int64
	for _, s := range p.PublishShop {
		if s.UserName == user {
			count++
			if s.Status != nil && *s.Status == 1 && s.ItemID > 0 {
				item = s.ItemID
			}
		}
	}
	return item, count == 1 && item > 0
}

func (m *marketplaceManager) reconcileCreate(ctx context.Context, api *xgjClient, j MarketplaceJob) error {
	created, err := time.Parse(time.RFC3339, j.CreatedAt)
	if err != nil {
		return m.deferJob(j.ID, "attention", "创建时间无效，无法安全核对远端商品", 0)
	}
	var matches []int64
	seen := map[int64]bool{}
	expectedCount := -1
	for page := 1; page <= 20; page++ {
		var data struct {
			List     []marketplaceProduct `json:"list"`
			Count    *int                 `json:"count"`
			PageNo   int                  `json:"page_no"`
			PageSize int                  `json:"page_size"`
		}
		err = api.call(ctx, "/api/open/product/list", map[string]any{"page_no": page, "page_size": 100, "update_time": []int64{created.Add(-24 * time.Hour).Unix(), m.now().Unix()}}, &data)
		if err != nil {
			return m.readFailure(j.ID, err)
		}
		if data.List == nil || data.Count == nil || *data.Count < 0 || data.PageNo != page || data.PageSize != 100 || len(data.List) > 100 {
			return m.readFailure(j.ID, errors.New("商品列表响应不完整，尚不能确认创建结果"))
		}
		if expectedCount < 0 {
			expectedCount = *data.Count
		}
		if expectedCount != *data.Count || len(data.List) != min(100, max(0, expectedCount-(page-1)*100)) {
			return m.readFailure(j.ID, errors.New("远端商品列表已变化或分页不完整，稍后重新核对"))
		}
		for _, p := range data.List {
			if seen[p.ProductID] {
				return m.readFailure(j.ID, errors.New("远端商品分页重复，稍后重新核对"))
			}
			seen[p.ProductID] = true
			if p.OuterID == j.OuterID && p.ProductID > 0 {
				matches = append(matches, p.ProductID)
			}
		}
		if len(matches) > 1 {
			return m.deferJob(j.ID, "attention", "远端发现多个相同商家编码的商品，请在闲管家核对；不会继续创建", 0)
		}
		if page*100 >= *data.Count {
			break
		}
		if len(data.List) == 0 || page == 20 {
			return m.deferJob(j.ID, "create_unknown", "远端商品列表尚未完整核对，不会重复创建", 30*time.Minute)
		}
	}
	if len(matches) == 1 {
		return m.change(j.ID, func(j *MarketplaceJob) {
			j.ProductID = strconv.FormatInt(matches[0], 10)
			j.Status, j.Error, j.NextRunAt = "created", "", ""
			j.Attempts = 0
		})
	}
	return m.deferJob(j.ID, "create_unknown", "尚未找到该商家编码的商品，继续核对；创建结果不明时不会再次提交", 30*time.Minute)
}

func (m *marketplaceManager) confirmOrPublish(ctx context.Context, api *xgjClient, j MarketplaceJob) error {
	id, err := strconv.ParseInt(j.ProductID, 10, 64)
	if err != nil || id <= 0 {
		return m.deferJob(j.ID, "attention", "商品编号无效，无法核实上架结果", 0)
	}
	var p marketplaceProduct
	if err = api.call(ctx, "/api/open/product/detail", map[string]any{"product_id": id}, &p); err != nil {
		return m.readFailure(j.ID, err)
	}
	if p.ProductID != id || p.OuterID != j.OuterID {
		return m.deferJob(j.ID, "attention", "远端商品编号或商家编码与任务不一致，已停止处理", 0)
	}
	if item, ok := marketplacePublished(p, j.ShopUserName); ok {
		return m.change(j.ID, func(j *MarketplaceJob) {
			j.Status, j.Error, j.NextRunAt = "published", "", ""
			j.ItemID = strconv.FormatInt(item, 10)
			j.ItemURL = "https://www.goofish.com/item?id=" + j.ItemID
			j.Attempts = 0
		})
	}
	if p.PublishStatus != nil && (*p.PublishStatus == 9 || *p.PublishStatus == 4 || *p.PublishStatus == 5 || *p.PublishStatus == -1) || p.ProductStatus == -1 || p.ProductStatus == 31 || p.ProductStatus == 33 || p.ProductStatus == 36 {
		return m.deferJob(j.ID, "attention", "闲管家返回发布异常、下架或不可操作状态，请在商品详情核对原因", 0)
	}
	if j.PublishIssuedAt != "" || j.Status == "confirming" || j.Status == "publishing" {
		start, _ := time.Parse(time.RFC3339, j.PublishIssuedAt)
		if !start.IsZero() && m.now().Sub(start) > 24*time.Hour {
			return m.deferJob(j.ID, "attention", "已持续核对 24 小时仍未确认上架，请在闲管家查看商品状态；不会重复创建", 0)
		}
		return m.deferJob(j.ID, "confirming", "已提交上架，等待指定店铺的商品编号与销售中状态", time.Minute)
	}
	if p.PublishStatus == nil || *p.PublishStatus != 2 || p.ProductStatus != 21 {
		return m.deferJob(j.ID, "attention", "远端状态尚不能确认可以上架，请核对商品详情", 0)
	}
	selected := 0
	for _, shop := range p.PublishShop {
		if shop.UserName == j.ShopUserName {
			if shop.Status == nil || *shop.Status != 1 {
				return m.deferJob(j.ID, "attention", "目标店铺未被选中，请核对远端商品资料", 0)
			}
			selected++
		}
	}
	if selected != 1 {
		return m.deferJob(j.ID, "attention", "远端商品缺少唯一的目标店铺，请核对后继续", 0)
	}
	t, ok := m.app.transfers.job(j.TransferID)
	if !ok || marketplaceTransferReady(t) != nil || t.BundleSHA256 != j.BundleSHA256 {
		return m.deferJob(j.ID, "created", "等待原任务的双网盘分享恢复有效后继续上架", 5*time.Minute)
	}
	if err = m.checkShop(ctx, api, j.ShopUserName); err != nil {
		return m.readFailure(j.ID, err)
	}
	if err = m.change(j.ID, func(j *MarketplaceJob) {
		j.Baidu, j.Quark = t.Outputs["baidu"].Share, t.Outputs["quark"].Share
		j.Status = "publishing"
		j.Error = ""
		j.PublishIssuedAt = m.nowString()
		j.NextRunAt = ""
	}); err != nil {
		return err
	}
	err = api.call(ctx, "/api/open/product/publish", map[string]any{"product_id": id, "user_name": []string{j.ShopUserName}}, &struct{}{})
	if err != nil {
		var e *xgjError
		if errors.As(err, &e) && !e.Ambiguous {
			return m.change(j.ID, func(j *MarketplaceJob) { j.Status, j.Error = "attention", err.Error(); j.PublishIssuedAt = "" })
		}
		return m.deferJob(j.ID, "confirming", "上架请求结果尚未确认，正在查询指定店铺状态", time.Minute)
	}
	return m.deferJob(j.ID, "confirming", "上架请求已受理，等待闲鱼实际发布结果", 30*time.Second)
}

func (m *marketplaceManager) retry(id string) error {
	m.opMu.Lock()
	defer m.opMu.Unlock()
	return m.change(id, func(j *MarketplaceJob) {
		if j.Status == "published" {
			return
		}
		j.Error, j.NextRunAt = "", ""
		j.Attempts = 0
		if (j.CreateIssuedAt != "" && j.ProductID == "") || j.Status == "create_unknown" || j.Status == "creating" {
			j.Status = "create_unknown"
			return
		}
		if j.ProductID != "" {
			j.Status = "created"
			if j.PublishIssuedAt != "" {
				j.Status = "confirming"
			}
			return
		}
		j.Status = "waiting_materials"
		j.MetadataAttempts = 0
	})
}

func (m *marketplaceManager) checkShop(ctx context.Context, api *xgjClient, user string) error {
	var response struct {
		List []struct {
			UserName         string `json:"user_name"`
			IsValid          bool   `json:"is_valid"`
			AuthorizeExpires int64  `json:"authorize_expires"`
			ValidEndTime     int64  `json:"valid_end_time"`
		} `json:"list"`
	}
	if err := api.call(ctx, "/api/open/user/authorize/list", struct{}{}, &response); err != nil {
		return err
	}
	for _, s := range response.List {
		if s.UserName == user {
			if s.AuthorizeExpires <= 0 || s.ValidEndTime <= 0 {
				return errors.New("店铺授权或服务有效期资料不完整，请在闲管家核对")
			}
			if !s.IsValid || s.AuthorizeExpires <= m.now().Unix() || s.ValidEndTime <= m.now().Unix() {
				return errors.New("店铺授权或开放平台服务已到期，请在闲管家续订或重新授权")
			}
			return nil
		}
	}
	return errors.New("所选店铺未出现在该应用的授权店铺中，请重新检测并选择")
}
