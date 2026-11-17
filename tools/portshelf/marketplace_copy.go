package main

import (
	"context"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
)

type marketplaceCopy struct {
	Title   string `json:"title"`
	Content string `json:"content"`
}

// Only title/content are replaced; saved prices, images, location and IDs stay
// intact. RawMessage preserves 64-bit identifiers in the durable create payload.
func marketplaceCopyPayload(raw json.RawMessage, user, title, content string) (json.RawMessage, error) {
	var payload map[string]json.RawMessage
	var shops []map[string]json.RawMessage
	if json.Unmarshal(raw, &payload) != nil || json.Unmarshal(payload["publish_shop"], &shops) != nil {
		return nil, errors.New("原商品资料无效，无法更新文案")
	}
	count := 0
	for _, shop := range shops {
		var name string
		_ = json.Unmarshal(shop["user_name"], &name)
		if name == user {
			count++
			shop["title"], _ = json.Marshal(title)
			shop["content"], _ = json.Marshal(content)
		}
	}
	if count != 1 {
		return nil, errors.New("原商品的店铺资料不唯一，无法更新文案")
	}
	payload["publish_shop"], _ = json.Marshal(shops)
	if _, ok := payload["title"]; ok {
		payload["title"], _ = json.Marshal(title)
	}
	return xgjJSON(payload)
}

// refreshCopy updates one existing product. An uncertain write remains recorded;
// later calls only read it back, including after a process restart.
func (m *marketplaceManager) refreshCopy(ctx context.Context, id string) error {
	if !m.opMu.TryLock() {
		return errors.New("铺货队列正在处理，请稍后更新文案")
	}
	defer m.opMu.Unlock()
	j, ok := m.job(id)
	if !ok {
		return errors.New("铺货任务不存在")
	}
	if j.Status != "published" && j.Status != "attention" {
		return errors.New("请等待当前铺货操作完成后更新文案")
	}
	productID, err := strconv.ParseInt(j.ProductID, 10, 64)
	if err != nil || productID <= 0 {
		return errors.New("尚未确认远端商品编号")
	}
	m.mu.Lock()
	api, fingerprint := m.api, marketplaceFingerprint(m.creds)
	m.mu.Unlock()
	if api == nil || fingerprint != j.AccountFingerprint {
		return errors.New("请连接创建该商品时使用的闲管家应用")
	}
	if err = m.checkShop(ctx, api, j.ShopUserName); err != nil {
		return err
	}
	wanted := j.CopyUpdate
	if wanted == nil {
		t, found := m.app.transfers.job(j.TransferID)
		if !found || !hasSourceBundle(t) || !strings.EqualFold(t.Repo, j.Repo) || t.BundleSHA256 != j.BundleSHA256 {
			return errors.New("原游戏或分享包已变化，无法更新文案")
		}
		title, content, e := marketplaceBuyerCopy(t, j.Config)
		if e != nil {
			return e
		}
		wanted = &marketplaceCopy{Title: title, Content: content}
	}
	payload, err := marketplaceCopyPayload(j.Payload, j.ShopUserName, wanted.Title, wanted.Content)
	if err != nil {
		return err
	}
	read := func() (marketplaceProduct, string, string, error) {
		var p marketplaceProduct
		if e := api.call(ctx, xgjProductPath, map[string]any{"product_id": productID}, &p); e != nil {
			return p, "", "", e
		}
		count, title, content := 0, "", ""
		for _, shop := range p.PublishShop {
			if shop.UserName == j.ShopUserName {
				count++
				title, content = shop.Title, shop.Content
			}
		}
		if p.ProductID != productID || p.OuterID != j.OuterID || p.ProductStatus == -1 || count != 1 || title == "" || content == "" {
			return p, "", "", errors.New("远端商品、商家编码或店铺资料不匹配，未修改")
		}
		return p, title, content, nil
	}
	p, title, content, err := read()
	if err != nil {
		return err
	}
	if title != wanted.Title || content != wanted.Content {
		if j.CopyUpdate != nil {
			return errors.New("文案更新结果仍待闲管家确认，再次点击只会查询，不会重复创建或上架")
		}
		if title != j.Title || content != j.Content {
			return errors.New("商品文案已在闲管家修改，已保留远端内容，请先核对")
		}
		if err = m.change(id, func(j *MarketplaceJob) { j.CopyUpdate = wanted }); err != nil {
			return err
		}
		var receipt struct {
			ProductID int64 `json:"product_id"`
		}
		err = api.call(ctx, xgjEditPath, map[string]any{
			"product_id": productID, "title": wanted.Title,
			"publish_shop": []map[string]string{{"user_name": j.ShopUserName, "title": wanted.Title, "content": wanted.Content}},
		}, &receipt)
		if err != nil {
			var providerError *xgjError
			if errors.As(err, &providerError) && !providerError.Ambiguous {
				if saveErr := m.change(id, func(j *MarketplaceJob) { j.CopyUpdate = nil }); saveErr != nil {
					return saveErr
				}
				return err
			}
			return errors.New("文案请求结果尚未确认，请点击核对文案；不会重复创建或上架")
		}
		if receipt.ProductID != productID {
			return errors.New("文案接口返回的商品编号不匹配，请点击核对文案")
		}
		p, title, content, err = read()
		if err != nil || title != wanted.Title || content != wanted.Content {
			return errors.New("文案请求已提交，等待闲管家同步，请稍后点击核对文案")
		}
	}
	return m.change(id, func(j *MarketplaceJob) {
		j.Title, j.Content, j.Payload = wanted.Title, wanted.Content, payload
		j.CopyUpdate, j.CopyUpdatedAt = nil, m.nowString()
		if _, published := marketplacePublished(p, j.ShopUserName); !published && j.Status == "published" {
			j.Status, j.Error = "attention", "闲管家文案已更新；远端商品当前未确认在售，未提交上架"
		}
	})
}
