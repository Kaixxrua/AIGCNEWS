<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

<template>
  <div class="legal-page">
    <div class="legal-card">
      <!-- 返回按钮 -->
      <button class="back-btn" @click="router.back()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
          <polyline points="15,18 9,12 15,6"/>
        </svg>
        返回
      </button>

      <h1 class="legal-title">隐私政策</h1>
      <p class="legal-meta">最后更新：2026年3月</p>

      <div class="legal-body">
        <section>
          <h2>我们收集哪些信息</h2>
          <p>
            <strong>我们不会收集您的多余隐私信息。</strong>本平台仅在您注册账号时收集以下最低限度的必要信息：
          </p>
          <ul>
            <li><strong>邮箱地址</strong>：用于账号注册、登录验证及服务通知（如您订阅了简报推送）。</li>
            <li><strong>密码（哈希存储）</strong>：您的密码经过不可逆加密（bcrypt）后存储，我们无法还原您的明文密码。</li>
            <li><strong>访问日志</strong>：我们通过 IP 地址统计今日独立访客数量，用于平台运营数据，该数据在 48 小时后自动清除，且不与您的账号信息关联。</li>
          </ul>
        </section>

        <section>
          <h2>AI 对话中的数据处理</h2>
          <div class="highlight-block">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <p>
              您在"新对话"中输入的内容，会被<strong>匿名化处理</strong>后发送至第三方大型语言模型（LLM）提供商（如 OpenAI、Anthropic 等）用于生成回答。本平台不会在请求中附带您的账号信息或个人标识。
            </p>
          </div>
          <p class="warning-text">
            ⚠️ <strong>请勿在对话中输入个人隐私信息（如身份证号、手机号、银行卡号）或商业机密内容。</strong>该部分数据将受第三方 LLM 服务商的隐私政策约束，超出本平台控制范围。
          </p>
        </section>

        <section>
          <h2>我们如何使用您的信息</h2>
          <ul>
            <li>邮箱地址：用于登录验证、发送您订阅的简报内容（仅在您主动订阅后）。</li>
            <li>对话记录：存储在本平台服务器，用于展示您的历史对话记录，系统会定期自动清理超过保留期限的记录。</li>
            <li>我们<strong>不会</strong>将您的任何信息出售或租赁给第三方。</li>
            <li>我们<strong>不会</strong>使用您的对话内容用于广告投放或商业画像分析。</li>
          </ul>
        </section>

        <section>
          <h2>数据存储与安全</h2>
          <p>
            您的账号数据存储于本平台的私有服务器（MySQL 数据库），连接通过加密传输（HTTPS/TLS）保护。我们采取合理的技术措施保护您的数据，但无法保证 100% 的绝对安全性。
          </p>
          <p>
            对话记录采用 LRU（最近最少使用）策略自动管理，每个账号最多保留最近 10 个会话，每个会话保留最近 10 条消息，超出部分将自动清除。
          </p>
        </section>

        <section>
          <h2>Cookie 与本地存储</h2>
          <p>
            本平台使用浏览器 <code>localStorage</code> 存储您的登录凭证（JWT Token），用于保持登录状态。我们不使用第三方 Cookie 追踪您的行为。
          </p>
        </section>

        <section>
          <h2>您的权利</h2>
          <p>您可以随时：</p>
          <ul>
            <li>在平台内删除您的对话历史记录。</li>
            <li>取消简报邮件订阅（在简报中心操作）。</li>
            <li>联系我们申请删除您的账号及相关数据。</li>
          </ul>
        </section>

        <section>
          <h2>联系我们</h2>
          <p>如有关于隐私的任何疑问，请通过以下方式联系：</p>
          <div class="contact-block">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
            <a href="mailto:kaixxrua@gmail.com">kaixxrua@gmail.com</a>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.legal-page {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  display: flex;
  justify-content: center;
  padding: 32px 24px 48px;
  box-sizing: border-box;
}

.legal-card {
  width: 100%;
  max-width: 720px;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #78716c;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px 0;
  margin-bottom: 24px;
  transition: color 0.2s;
}
.back-btn:hover {
  color: #44403c;
}

.legal-title {
  font-size: 26px;
  font-weight: 700;
  color: #1c1917;
  margin: 0 0 8px;
  font-family: 'Playfair Display', serif;
}

.legal-meta {
  font-size: 12px;
  color: #a8a29e;
  margin: 0 0 32px;
}

.legal-body {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.legal-body section h2 {
  font-size: 15px;
  font-weight: 600;
  color: #292524;
  margin: 0 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(168, 162, 158, 0.15);
}

.legal-body section p {
  font-size: 14px;
  line-height: 1.75;
  color: #57534e;
  margin: 0 0 8px;
}

.legal-body section p:last-child {
  margin-bottom: 0;
}

.legal-body ul {
  margin: 8px 0 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.legal-body ul li {
  font-size: 14px;
  line-height: 1.7;
  color: #57534e;
}

.legal-body strong {
  color: #292524;
  font-weight: 600;
}

.legal-body code {
  background: rgba(245, 245, 244, 0.9);
  border: 1px solid rgba(168, 162, 158, 0.2);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  color: #44403c;
}

/* 重要提示块 */
.highlight-block {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  background: rgba(6, 182, 212, 0.04);
  border: 1px solid rgba(6, 182, 212, 0.15);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
  color: #57534e;
}

.highlight-block svg {
  flex-shrink: 0;
  margin-top: 2px;
  color: #06b6d4;
}

.highlight-block p {
  margin: 0 !important;
  font-size: 14px;
  line-height: 1.7;
}

.warning-text {
  font-size: 13px !important;
  color: #78716c !important;
  background: rgba(251, 146, 60, 0.05);
  border: 1px solid rgba(251, 146, 60, 0.15);
  border-radius: 8px;
  padding: 10px 14px;
  margin-top: 0 !important;
}

.contact-block {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 10px 16px;
  background: rgba(245, 245, 244, 0.8);
  border: 1px solid rgba(168, 162, 158, 0.15);
  border-radius: 10px;
  font-size: 13px;
  color: #57534e;
}

.contact-block a {
  color: #44403c;
  text-decoration: none;
  font-weight: 500;
}

.contact-block a:hover {
  text-decoration: underline;
}
</style>
