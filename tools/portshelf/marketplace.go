package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"
)

type MarketplaceProperty struct {
	PropertyID   string `json:"property_id"`
	PropertyName string `json:"property_name"`
	ValueID      string `json:"value_id"`
	ValueName    string `json:"value_name"`
}

type MarketplaceConfig struct {
	Enabled      bool                  `json:"enabled"`
	ShopUserName string                `json:"shopUserName"`
	ItemBizType  int                   `json:"itemBizType"`
	SpBizType    int                   `json:"spBizType"`
	CategoryID   string                `json:"categoryId"`
	Properties   []MarketplaceProperty `json:"properties"`
	Province     int                   `json:"province"`
	City         int                   `json:"city"`
	District     int                   `json:"district"`
	PriceFen     int64                 `json:"priceFen"`
	Stock        int                   `json:"stock"`
	TitlePrefix  string                `json:"titlePrefix"`
}

type MarketplaceJob struct {
	ID                 string            `json:"id"`
	TransferID         string            `json:"transferId"`
	Repo               string            `json:"repo"`
	Title              string            `json:"title"`
	Content            string            `json:"content"`
	PosterURL          string            `json:"posterUrl"`
	ShopUserName       string            `json:"shopUserName"`
	PriceFen           int64             `json:"priceFen"`
	Status             string            `json:"status"`
	Error              string            `json:"error,omitempty"`
	ProductID          string            `json:"productId,omitempty"`
	ItemID             string            `json:"itemId,omitempty"`
	ItemURL            string            `json:"itemUrl,omitempty"`
	OuterID            string            `json:"outerId"`
	AccountFingerprint string            `json:"accountFingerprint"`
	Config             MarketplaceConfig `json:"config"`
	Payload            json.RawMessage   `json:"payload,omitempty"`
	BundleSHA256       string            `json:"bundleSha256"`
	Baidu              CloudShare        `json:"baidu"`
	Quark              CloudShare        `json:"quark"`
	CreatedAt          string            `json:"createdAt"`
	UpdatedAt          string            `json:"updatedAt"`
	NextRunAt          string            `json:"nextRunAt,omitempty"`
	PublishIssuedAt    string            `json:"publishIssuedAt,omitempty"`
	CreateIssuedAt     string            `json:"createIssuedAt,omitempty"`
	MetadataAttempts   int               `json:"metadataAttempts,omitempty"`
	Attempts           int               `json:"attempts,omitempty"`
}

type marketplaceState struct {
	Version int               `json:"version"`
	Config  MarketplaceConfig `json:"config"`
	Jobs    []MarketplaceJob  `json:"jobs"`
}

type marketplaceManager struct {
	mu         sync.Mutex
	opMu       sync.Mutex
	app        *App
	state      marketplaceState
	creds      XGJCredentials
	api        *xgjClient
	shops      []XGJShop
	activeID   string
	activeStop context.CancelFunc
	storeError string
	wake       chan struct{}
	done       chan struct{}
	now        func() time.Time
	write      func(string, string, []byte) error
}

func marketplaceText(value string, limit int, multiline bool) bool {
	if !utf8.ValidString(value) || utf8.RuneCountInString(value) > limit {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) && !(multiline && r == '\n') {
			return false
		}
	}
	return true
}

func validateMarketplaceConfig(c MarketplaceConfig, complete bool) error {
	if c.ItemBizType != 2 || c.SpBizType < 0 || c.SpBizType > 99 || c.PriceFen < 0 || c.PriceFen > 9999999900 || c.Stock < 0 || c.Stock > 399960 || len(c.Properties) > 40 {
		return errors.New("商品设置无效；使用普通商品，售价最多 99999999 元，库存最多 399960")
	}
	if !marketplaceText(c.ShopUserName, 128, false) || !marketplaceText(c.CategoryID, 128, false) || !marketplaceText(c.TitlePrefix, 20, false) || marketplaceWidth(c.TitlePrefix) > 40 {
		return errors.New("店铺、类目或标题前缀无效")
	}
	seen := map[string]bool{}
	for _, p := range c.Properties {
		if p.PropertyID == "" || p.ValueID == "" || seen[p.PropertyID] || !marketplaceText(p.PropertyID, 128, false) || !marketplaceText(p.ValueID, 128, false) || !marketplaceText(p.PropertyName, 100, false) || !marketplaceText(p.ValueName, 100, false) {
			return errors.New("商品属性无效或重复")
		}
		seen[p.PropertyID] = true
	}
	for _, n := range []int{c.Province, c.City, c.District} {
		if n != 0 && (n < 100000 || n > 999999) {
			return errors.New("发货地须使用六位省市区编码，可从已保存地址选择")
		}
	}
	if complete && (strings.TrimSpace(c.ShopUserName) == "" || c.SpBizType == 0 || c.CategoryID == "" || c.Province == 0 || c.City == 0 || c.District == 0 || c.PriceFen == 0 || c.Stock == 0) {
		return errors.New("请先选择店铺、行业、类目和发货地址，并设置售价与库存")
	}
	return nil
}

func marketplaceWidth(value string) int {
	n := 0
	for _, r := range value {
		if r > 127 {
			n += 2
		} else {
			n++
		}
	}
	return n
}
func marketplaceTrim(value string, limit int) string {
	n := 0
	var b strings.Builder
	for _, r := range value {
		w := 1
		if r > 127 {
			w = 2
		}
		if n+w > limit {
			break
		}
		b.WriteRune(r)
		n += w
	}
	return b.String()
}

func cloneMarketplaceState(s marketplaceState) marketplaceState {
	data, _ := json.Marshal(s)
	var copy marketplaceState
	_ = json.Unmarshal(data, &copy)
	return copy
}

func newMarketplace(a *App) (*marketplaceManager, error) {
	m := &marketplaceManager{app: a, state: marketplaceState{Version: 1, Config: MarketplaceConfig{ItemBizType: 2, Properties: []MarketplaceProperty{}}, Jobs: []MarketplaceJob{}}, shops: []XGJShop{}, wake: make(chan struct{}, 1), done: make(chan struct{}), now: time.Now, write: automationWriteFile}
	f, err := os.Open(filepath.Join(a.lib.root, "marketplace.json"))
	if errors.Is(err, os.ErrNotExist) {
		return m, nil
	}
	if err != nil {
		return nil, errors.New("无法读取闲管家铺货记录")
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, (32<<20)+1))
	if err != nil || len(b) > 32<<20 || json.Unmarshal(b, &m.state) != nil || m.state.Version != 1 || len(m.state.Jobs) > maxTransferJobs || validateMarketplaceConfig(m.state.Config, m.state.Config.Enabled) != nil {
		return nil, errors.New("闲管家铺货记录无效，请先备份 marketplace.json")
	}
	ids, outer := map[string]bool{}, map[string]bool{}
	for i := range m.state.Jobs {
		j := &m.state.Jobs[i]
		if !sessionTokenPattern.MatchString(j.ID) || ids[j.ID] || !sessionTokenPattern.MatchString(j.TransferID) || j.OuterID == "" || len(j.OuterID) > 64 || outer[j.OuterID] || validateMarketplaceConfig(j.Config, true) != nil || !validMarketplaceStatus(j.Status) {
			return nil, errors.New("闲管家任务记录无效")
		}
		if _, err := parseRepo(j.Repo); err != nil {
			return nil, errors.New("闲管家任务仓库无效")
		}
		for _, value := range []string{j.CreatedAt, j.UpdatedAt, j.NextRunAt, j.PublishIssuedAt, j.CreateIssuedAt} {
			if value != "" {
				if _, err := time.Parse(time.RFC3339, value); err != nil {
					return nil, errors.New("闲管家任务时间无效")
				}
			}
		}
		ids[j.ID], outer[j.OuterID] = true, true
		// A process may have died after the remote side effect but before its
		// receipt was saved. Recovery always reads; it never repeats creation.
		if j.Status == "creating" {
			j.Status = "create_unknown"
		}
		if j.Status == "publishing" {
			j.Status = "confirming"
		}
	}
	return m, nil
}

func validMarketplaceStatus(s string) bool {
	switch s {
	case "waiting_materials", "queued", "creating", "create_unknown", "created", "publishing", "confirming", "published", "attention":
		return true
	}
	return false
}
func (m *marketplaceManager) credentialsSnapshot() XGJCredentials {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.creds
}
func (m *marketplaceManager) restoreCredentials(c XGJCredentials) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.creds = c
	m.api = nil
	m.shops = []XGJShop{}
	if c.AppKey != "" {
		m.api = newXGJClient(c)
	}
}
func (m *marketplaceManager) notify() {
	if m.wake == nil {
		return
	}
	select {
	case m.wake <- struct{}{}:
	default:
	}
}
func (m *marketplaceManager) nowString() string { return m.now().UTC().Format(time.RFC3339) }

func (m *marketplaceManager) saveLocked(next marketplaceState) error {
	b, err := json.MarshalIndent(next, "", "  ")
	if err != nil || len(b) > 32<<20 {
		return errors.New("闲管家任务记录过大")
	}
	if err = m.write(m.app.lib.root, "marketplace.json", b); err != nil {
		m.storeError = "无法保存闲管家任务进度，请检查磁盘与权限"
		return errors.New(m.storeError)
	}
	m.state, m.storeError = next, ""
	return nil
}
func (m *marketplaceManager) change(id string, f func(*MarketplaceJob)) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	next := cloneMarketplaceState(m.state)
	for i := range next.Jobs {
		if next.Jobs[i].ID == id {
			f(&next.Jobs[i])
			next.Jobs[i].UpdatedAt = m.nowString()
			return m.saveLocked(next)
		}
	}
	return errors.New("铺货任务不存在")
}
func (m *marketplaceManager) job(id string) (MarketplaceJob, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, j := range cloneMarketplaceState(m.state).Jobs {
		if j.ID == id {
			return j, true
		}
	}
	return MarketplaceJob{}, false
}

func marketplaceFingerprint(c XGJCredentials) string {
	if c.AppKey == "" {
		return ""
	}
	h := sha256.Sum256([]byte(c.AppKey))
	return hex.EncodeToString(h[:])
}
func marketplaceOuterID(c XGJCredentials, config MarketplaceConfig, t TransferJob) string {
	h := sha256.Sum256([]byte(strings.Join([]string{c.AppKey, config.ShopUserName, strings.ToLower(t.Repo), t.Version, t.Arch, t.BundleSHA256}, "\x00")))
	return "PS-" + hex.EncodeToString(h[:24])
}

func (m *marketplaceManager) collect() (int, error) {
	transfers, problem := m.app.transfers.snapshot()
	if problem != "" {
		return 0, errors.New(problem)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if validateMarketplaceConfig(m.state.Config, true) != nil || !validXGJCredentials(m.creds) {
		return 0, errors.New("请先连接闲管家并保存完整发布规则")
	}
	next := cloneMarketplaceState(m.state)
	seen := map[string]bool{}
	for _, j := range next.Jobs {
		seen[j.OuterID] = true
	}
	added := 0
	for _, t := range transfers {
		if t.Status != "done" || !hasSourceBundle(t) {
			continue
		}
		key := marketplaceOuterID(m.creds, next.Config, t)
		if seen[key] {
			continue
		}
		if len(next.Jobs) >= maxTransferJobs {
			return 0, errors.New("铺货任务已达 2000 条，请先导出记录")
		}
		config := next.Config
		config.Enabled = false
		next.Jobs = append(next.Jobs, MarketplaceJob{ID: randomID(), TransferID: t.ID, Repo: t.Repo, ShopUserName: config.ShopUserName, PriceFen: config.PriceFen, Status: "waiting_materials", OuterID: key, AccountFingerprint: marketplaceFingerprint(m.creds), Config: config, BundleSHA256: t.BundleSHA256, CreatedAt: m.nowString(), UpdatedAt: m.nowString()})
		seen[key] = true
		added++
	}
	if added > 0 {
		if err := m.saveLocked(next); err != nil {
			return 0, err
		}
	}
	return added, nil
}

func marketplaceTransferReady(t TransferJob) error {
	if t.Status != "done" || !hasSourceBundle(t) {
		return errors.New("等待安装包及对应源码分享包完成")
	}
	for _, provider := range []string{"baidu", "quark"} {
		o := t.Outputs[provider]
		if o.Status != "done" || o.File.ID == "" || o.Session == "" || o.Error != "" || o.NeedsAttention || o.PayloadSHA256 != t.BundleSHA256 || !usableCloudShare(provider, o.Share) {
			return fmt.Errorf("等待 %s 网盘分享完成，或现有分享已过期", map[string]string{"baidu": "百度", "quark": "夸克"}[provider])
		}
	}
	return nil
}

func marketplaceMaterialsReady(t TransferJob) bool {
	return readyTransferDetails(t) && validChineseDescription(t.Description) && validGamePoster(t.Repo, t.PosterURL) && strings.HasPrefix(t.PosterURL, "https://aigcnews.cn/api/media/site/game-posters/")
}

func marketplacePayload(t TransferJob, c MarketplaceConfig, outer string) (json.RawMessage, string, string, error) {
	if err := marketplaceTransferReady(t); err != nil {
		return nil, "", "", err
	}
	if !marketplaceMaterialsReady(t) {
		return nil, "", "", errors.New("等待中文简介和可公开访问的已核验游戏图片")
	}
	name := t.GameNameZh
	if name == "" {
		name = t.Name
	}
	if name == "" {
		name = t.Repo
	}
	title := marketplaceTrim(strings.TrimSpace(c.TitlePrefix+" "+name+" · 开源项目文件与源码"), 60)
	content := strings.Join([]string{t.Description, "", "项目：" + t.Repo, "发布版本：" + t.Version, "安装包平台：Windows " + t.Arch, "项目支持系统：" + systemDescription(t.SupportedSystems), "内容：上游公开发布安装包、对应版本源码及来源说明。通过百度网盘和夸克网盘交付。", "运行要求：" + t.DataNote, "使用说明：" + t.Guide, "项目来源：https://github.com/" + t.Repo, "源码版本：" + t.SourceCommit, "请按上游许可使用；若项目需要原版游戏数据，须自行准备。"}, "\n")
	if marketplaceWidth(content) > 5000 || !marketplaceText(content, 5000, true) {
		return nil, "", "", errors.New("商品资料超过平台长度限制，请整理简介或运行说明后重试")
	}
	properties := append([]MarketplaceProperty{}, c.Properties...)
	payload := map[string]any{"item_biz_type": c.ItemBizType, "sp_biz_type": c.SpBizType, "channel_cat_id": c.CategoryID, "channel_pv": properties, "price": c.PriceFen, "express_fee": 0, "stock": c.Stock, "outer_id": outer, "stuff_status": 0, "publish_shop": []map[string]any{{"user_name": c.ShopUserName, "province": c.Province, "city": c.City, "district": c.District, "title": title, "content": content, "images": []string{t.PosterURL}, "express_way": 5}}}
	b, err := xgjJSON(payload)
	return b, title, content, err
}
