package main

import (
	"errors"
	"strings"
	"time"
)

// This prepares buyer text only. AppKey product publication does not configure
// the website's order-delivery binding, so never report it as enabled here.
func (m *marketplaceManager) deliveryPreview(id string) (string, error) {
	j, ok := m.job(id)
	if !ok {
		return "", errors.New("铺货任务不存在")
	}
	t, ok := m.app.transfers.job(j.TransferID)
	if !ok || !strings.EqualFold(t.Repo, j.Repo) || t.BundleSHA256 != j.BundleSHA256 {
		return "", errors.New("原游戏或分享包已变化，请先核对交付文件")
	}
	if err := marketplaceTransferReady(t); err != nil {
		return "", err
	}
	_, content, err := marketplaceBuyerCopy(t, MarketplaceConfig{})
	if err != nil {
		return "", err
	}
	lines := []string{"感谢购买！", "", content}
	for _, provider := range []string{"baidu", "quark"} {
		share := t.Outputs[provider].Share
		lines = append(lines, "", map[string]string{"baidu": "百度网盘", "quark": "夸克网盘"}[provider]+"："+share.URL)
		if share.Code != "" {
			if !marketplaceText(share.Code, 32, false) {
				return "", errors.New("网盘提取码格式无效，请先核对分享")
			}
			lines = append(lines, "提取码："+share.Code)
		}
		if share.ExpiresAt != "" {
			expires, _ := time.Parse(time.RFC3339, share.ExpiresAt)
			lines = append(lines, "有效期至："+expires.In(time.FixedZone("Asia/Shanghai", 8*60*60)).Format("2006-01-02 15:04")+"（北京时间）")
		}
	}
	lines = append(lines, "", "两个网盘的文件内容相同，任选一个下载。下载后解压，说明文件在压缩包内。")
	return strings.Join(lines, "\n"), nil
}
