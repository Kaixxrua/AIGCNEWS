package main

import (
	"context"
	"errors"
	"net/http"
	"strings"
)

func (m *marketplaceManager) status() map[string]any {
	m.mu.Lock()
	config := cloneMarketplaceState(m.state).Config
	connected := m.api != nil
	shops := append([]XGJShop{}, m.shops...)
	running := m.activeID != ""
	problem := m.storeError
	m.mu.Unlock()
	storage := m.app.credentialStorageStatus()
	return map[string]any{"config": config, "connected": connected, "shops": shops, "running": running, "error": problem, "credentialSaved": connected && storage.Saved, "credentialStorageSupported": storage.Supported}
}

// Lock order is operation -> credential -> marketplace. Vault persistence must
// finish before an account replacement becomes available to the worker.
func (m *marketplaceManager) setCredentials(c XGJCredentials, api *xgjClient, shops []XGJShop) error {
	m.opMu.Lock()
	defer m.opMu.Unlock()
	credentials := m.app.credentials
	if credentials != nil {
		credentials.mu.Lock()
		defer credentials.mu.Unlock()
		if credentials.loadFailed {
			return errors.New("已保存凭据暂时不可读，请先恢复凭据存储；不会覆盖原网盘授权")
		}
	}
	m.mu.Lock()
	oldCreds, oldAPI, oldShops := m.creds, m.api, m.shops
	m.creds, m.api, m.shops = c, api, shops
	m.mu.Unlock()
	if credentials != nil && credentials.remember && credentials.vault.available {
		if err := credentials.vault.save(credentials.snapshotLocked()); err != nil {
			m.mu.Lock()
			m.creds, m.api, m.shops = oldCreds, oldAPI, oldShops
			m.mu.Unlock()
			return errors.New("保存闲管家授权失败，原授权已保留")
		}
		credentials.hasVault = true
	}
	m.notify()
	return nil
}

func (m *marketplaceManager) lookupClient() (*xgjClient, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.api == nil {
		return nil, errors.New("请先填写 AppKey 和 AppSecret 并连接闲管家")
	}
	return m.api, nil
}

func (m *marketplaceManager) validateRemoteConfig(ctx context.Context, api *xgjClient, c MarketplaceConfig) error {
	if err := m.checkShop(ctx, api, c.ShopUserName); err != nil {
		return err
	}
	categories, err := api.listCategories(ctx, c.ItemBizType, c.SpBizType)
	if err != nil {
		return err
	}
	found := false
	for _, category := range categories {
		if category.ChannelCatID == c.CategoryID && category.SpBizType == c.SpBizType {
			found = true
			break
		}
	}
	if !found {
		return errors.New("所选类目与商品行业不匹配，请重新读取并选择类目")
	}
	selected := map[string]MarketplaceProperty{}
	for _, property := range c.Properties {
		selected[property.PropertyID] = property
	}
	visited, verified := map[string]bool{}, map[string]bool{}
	pending := []string{""}
	for len(pending) > 0 {
		id := pending[0]
		pending = pending[1:]
		if visited[id] {
			continue
		}
		visited[id] = true
		if len(visited) > 12 {
			return errors.New("商品属性层级过多，请在闲管家核对类目")
		}
		properties, err := api.listProperties(ctx, c.ItemBizType, c.SpBizType, c.CategoryID, id)
		if err != nil {
			return err
		}
		for _, property := range properties {
			choice, ok := selected[property.PropertyID]
			if !ok {
				if property.Required == 1 {
					return errors.New("请填写类目要求的商品属性")
				}
				continue
			}
			matched := false
			for _, value := range property.Items {
				if value.ValueID == choice.ValueID && value.ValueName == choice.ValueName && property.PropertyName == choice.PropertyName {
					matched = true
					verified[property.PropertyID] = true
					if value.SubPropertyID != "" {
						pending = append(pending, value.SubPropertyID)
					}
					break
				}
			}
			if !matched {
				return errors.New("商品属性值与当前类目不匹配，请刷新属性后保存")
			}
		}
	}
	if len(verified) != len(selected) {
		return errors.New("部分商品属性不属于当前类目，请重新选择")
	}
	return nil
}

func (m *marketplaceManager) configure(ctx context.Context, c MarketplaceConfig) error {
	if err := validateMarketplaceConfig(c, c.Enabled); err != nil {
		return err
	}
	if !c.Enabled {
		m.mu.Lock()
		if m.activeStop != nil {
			m.activeStop()
		}
		m.mu.Unlock()
	}
	m.opMu.Lock()
	defer m.opMu.Unlock()
	if c.Enabled {
		api, err := m.lookupClient()
		if err != nil {
			return err
		}
		if err = m.validateRemoteConfig(ctx, api, c); err != nil {
			return err
		}
	}
	m.mu.Lock()
	next := cloneMarketplaceState(m.state)
	next.Config = c
	err := m.saveLocked(next)
	m.mu.Unlock()
	if err == nil {
		m.notify()
	}
	return err
}

func (a *App) registerMarketplaceRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/marketplace", func(w http.ResponseWriter, r *http.Request) { reply(w, 200, a.marketplace.status()) })
	mux.HandleFunc("POST /api/marketplace/connect", func(w http.ResponseWriter, r *http.Request) {
		var c XGJCredentials
		if err := decode(w, r, &c); err != nil {
			fail(w, 400, err)
			return
		}
		if !validXGJCredentials(c) {
			fail(w, 400, errors.New("请填写有效的闲管家 AppKey 和 AppSecret"))
			return
		}
		api := newXGJClient(c)
		shops, err := api.listShops(r.Context())
		if err != nil {
			fail(w, 502, err)
			return
		}
		if err = a.marketplace.setCredentials(c, api, shops); err != nil {
			fail(w, 500, err)
			return
		}
		reply(w, 200, a.marketplace.status())
	})
	mux.HandleFunc("POST /api/marketplace/disconnect", func(w http.ResponseWriter, r *http.Request) {
		var body struct{}
		if err := decode(w, r, &body); err != nil {
			fail(w, 400, err)
			return
		}
		if err := a.marketplace.setCredentials(XGJCredentials{}, nil, []XGJShop{}); err != nil {
			fail(w, 500, err)
			return
		}
		reply(w, 200, a.marketplace.status())
	})
	mux.HandleFunc("POST /api/marketplace/check", func(w http.ResponseWriter, r *http.Request) {
		var body struct{}
		if err := decode(w, r, &body); err != nil {
			fail(w, 400, err)
			return
		}
		api, err := a.marketplace.lookupClient()
		if err != nil {
			fail(w, 409, err)
			return
		}
		shops, err := api.listShops(r.Context())
		if err != nil {
			fail(w, 502, err)
			return
		}
		a.marketplace.mu.Lock()
		if a.marketplace.api == api {
			a.marketplace.shops = shops
		}
		a.marketplace.mu.Unlock()
		reply(w, 200, a.marketplace.status())
	})
	mux.HandleFunc("POST /api/marketplace/config", func(w http.ResponseWriter, r *http.Request) {
		var c MarketplaceConfig
		if err := decode(w, r, &c); err != nil {
			fail(w, 400, err)
			return
		}
		if err := a.marketplace.configure(r.Context(), c); err != nil {
			fail(w, 400, err)
			return
		}
		reply(w, 200, a.marketplace.status())
	})
	mux.HandleFunc("POST /api/marketplace/categories", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			ItemBizType int `json:"itemBizType"`
			SpBizType   int `json:"spBizType"`
		}
		if err := decode(w, r, &body); err != nil {
			fail(w, 400, err)
			return
		}
		if body.ItemBizType != 2 || body.SpBizType < 0 || body.SpBizType > 99 {
			fail(w, 400, errors.New("商品类型或行业无效"))
			return
		}
		api, err := a.marketplace.lookupClient()
		if err != nil {
			fail(w, 409, err)
			return
		}
		items, err := api.listCategories(r.Context(), body.ItemBizType, body.SpBizType)
		if err != nil {
			fail(w, 502, err)
			return
		}
		reply(w, 200, map[string]any{"items": items})
	})
	mux.HandleFunc("POST /api/marketplace/properties", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			ItemBizType int    `json:"itemBizType"`
			SpBizType   int    `json:"spBizType"`
			CategoryID  string `json:"categoryId"`
			PropertyID  string `json:"propertyId"`
		}
		if err := decode(w, r, &body); err != nil {
			fail(w, 400, err)
			return
		}
		if body.ItemBizType == 0 {
			body.ItemBizType = 2
		}
		if body.ItemBizType != 2 || body.CategoryID == "" || !marketplaceText(body.CategoryID, 128, false) || !marketplaceText(body.PropertyID, 128, false) || body.SpBizType < 1 || body.SpBizType > 99 {
			fail(w, 400, errors.New("请先选择有效类目"))
			return
		}
		api, err := a.marketplace.lookupClient()
		if err != nil {
			fail(w, 409, err)
			return
		}
		items, err := api.listProperties(r.Context(), body.ItemBizType, body.SpBizType, body.CategoryID, body.PropertyID)
		if err != nil {
			fail(w, 502, err)
			return
		}
		reply(w, 200, map[string]any{"items": items})
	})
	mux.HandleFunc("POST /api/marketplace/addresses", func(w http.ResponseWriter, r *http.Request) {
		var body struct{}
		if err := decode(w, r, &body); err != nil {
			fail(w, 400, err)
			return
		}
		api, err := a.marketplace.lookupClient()
		if err != nil {
			fail(w, 409, err)
			return
		}
		items, err := api.listAddresses(r.Context(), 1)
		if err != nil {
			fail(w, 502, err)
			return
		}
		reply(w, 200, map[string]any{"items": items})
	})
	mux.HandleFunc("GET /api/marketplace/jobs", func(w http.ResponseWriter, r *http.Request) {
		a.marketplace.mu.Lock()
		jobs := cloneMarketplaceState(a.marketplace.state).Jobs
		problem := a.marketplace.storeError
		a.marketplace.mu.Unlock()
		reply(w, 200, map[string]any{"jobs": jobs, "error": problem})
	})
	for _, path := range []string{"/api/marketplace/run", "/api/marketplace/enqueue"} {
		mux.HandleFunc("POST "+path, func(w http.ResponseWriter, r *http.Request) {
			var body struct{}
			if err := decode(w, r, &body); err != nil {
				fail(w, 400, err)
				return
			}
			a.marketplace.opMu.Lock()
			added, err := a.marketplace.collect()
			a.marketplace.opMu.Unlock()
			if err != nil {
				fail(w, 409, err)
				return
			}
			a.marketplace.notify()
			reply(w, 202, map[string]any{"added": added})
		})
	}
	mux.HandleFunc("POST /api/marketplace/jobs/{id}/retry", func(w http.ResponseWriter, r *http.Request) {
		var body struct{}
		if err := decode(w, r, &body); err != nil {
			fail(w, 400, err)
			return
		}
		id := strings.TrimSpace(r.PathValue("id"))
		if err := a.marketplace.retry(id); err != nil {
			fail(w, 409, err)
			return
		}
		a.marketplace.notify()
		reply(w, 202, map[string]bool{"ok": true})
	})
}
