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

      <h1 class="legal-title">用户协议与免责声明</h1>
      <p class="legal-meta">最后更新：2026年3月 · 请在注册前仔细阅读本协议全文</p>

      <div class="legal-body">

        <!-- ── 一、AI 内容绝对免责 ── -->
        <section>
          <h2><span class="section-num">一</span>AI 生成内容免责声明（最重要）</h2>
          <div class="highlight-block highlight-block--warning">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16" class="shrink-0 mt-0.5"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <p><strong>本平台提供的 AI 资讯简报及 RAG 问答服务，底层依托于大语言模型（LLM）技术。受限于技术特性，大语言模型存在固有的"幻觉"（Hallucination）现象，即可能生成听起来合理但实际上错误、过时或虚构的内容。本平台不对生成内容的准确性、完整性、客观性及适用性作出任何明示或暗示的保证。</strong></p>
          </div>
          <p>平台提供的所有内容（含但不限于：代码片段、资讯摘要、数据分析、研究解读）<strong>仅供参考与学术交流，绝不构成任何投资建议、法律建议、医疗建议或专业工程建议。</strong></p>
          <p>用户若依据本平台生成内容做出任何决策（包括但不限于：投资操作、代码部署、商业判断、医疗决定），<strong>其直接损失、间接损失、偶然损失或连带损失，均由用户自行承担，本平台概不负责。</strong></p>
          <p>使用本平台即表明用户已充分知晓 AI 技术的局限性，并承诺在使用生成内容前进行独立核实。</p>
        </section>

        <!-- ── 二、用户行为红线 ── -->
        <section>
          <h2><span class="section-num">二</span>用户行为规范与禁止事项</h2>
          <p>用户在使用本平台 RAG 对话、资讯检索等交互功能时，承诺严格遵守以下行为规范：</p>
          <ul>
            <li>不得输入含有<strong>反动、分裂国家、颠覆政权</strong>等违反中国宪法及法律法规的内容；</li>
            <li>不得输入<strong>色情、淫秽、赌博、暴力、恐怖主义、仇恨言论</strong>等违法违规内容；</li>
            <li>不得输入<strong>虚假信息、诽谤他人、侵犯隐私</strong>的提示词；</li>
            <li>不得利用本平台实施<strong>Prompt 注入攻击（Prompt Injection）、越狱（Jailbreak）</strong>或其他方式试图绕过平台安全机制；</li>
            <li>不得使用本平台生成内容用于任何<strong>欺诈、诈骗或其他违法犯罪活动</strong>。</li>
          </ul>
          <p class="warning-text">⚠️ 如用户故意违反上述规定，诱导 AI 生成违法内容，<strong>一切法律责任由用户独立承担</strong>。平台有权在不通知的情况下立即封禁违规账号，保存相关日志，并依法向有关部门报告。</p>
        </section>

        <!-- ── 三、知识产权 ── -->
        <section>
          <h2><span class="section-num">三</span>知识产权声明</h2>
          <p><strong>对上游数据来源：</strong>本平台展示的原始论文（arXiv）、开源项目（GitHub）、科技新闻（Techmeme）、产品信息（Product Hunt）、社区讨论（Hacker News）等内容，其版权均归原作者或原始发布平台所有。本平台仅提供链接索引及 AI 辅助摘要，不主张对上述原始内容的所有权。若权利方认为本平台的展示方式侵犯了其合法权益，请联系我们（<a href="mailto:kaixxrua@gmail.com" class="inline-link">kaixxrua@gmail.com</a>），我们将在核实后第一时间下架处理。</p>
          <p><strong>对平台生成内容：</strong>用户在使用本平台 AI 生成的资讯简报、问答结果等内容时，若将其用于<strong>商业用途</strong>，需自行评估并承担可能引发的版权侵权风险，本平台不提供任何商业用途担保。</p>
          <p><strong>禁止爬取：</strong>未经本平台书面许可，严禁使用自动化脚本（爬虫）批量抓取本平台的简报数据、排行榜结果或其他 AI 生成内容，亦不得恶意高频调用本平台接口，否则本平台保留追究法律责任的权利。</p>
        </section>

        <!-- ── 四、服务变更与收费权利 ── -->
        <section>
          <h2><span class="section-num">四</span>服务变更、中断与收费权利</h2>
          <p>鉴于 AI 技术发展迅速及算力成本的不确定性，本平台保留以下权利，且无需就此对任何用户承担赔偿责任：</p>
          <ul>
            <li><strong>修改或限制服务</strong>：包括但不限于调整每日 AI 对话次数上限、降低采集频率、关闭特定功能模块；</li>
            <li><strong>暂停或终止服务</strong>：因技术故障、上游数据源封锁、政策原因或不可抗力，平台可随时暂停或终止部分乃至全部服务；</li>
            <li><strong>引入收费机制</strong>：平台未来可能对高级功能（如无限 RAG 问答、定制化订阅推送、优先级采集）收取费用，收费前将通过页面公告等形式提前通知用户；</li>
            <li><strong>修改本协议</strong>：本协议内容可能随时更新，重大变更将通过平台公告通知，用户继续使用本平台即视为接受最新条款。</li>
          </ul>
        </section>

        <!-- ── 五、账号安全与实名制 ── -->
        <section>
          <h2><span class="section-num">五</span>账号安全与责任归属</h2>
          <p>用户须妥善保管本平台账号及登录凭证（邮箱/密码/验证码）。<strong>用户账号下发生的所有行为（包括但不限于：发起对话、订阅邮件推送、使用 AI 功能），均视为用户本人的自主行为，由用户承担相应的法律责任。</strong>因用户自身原因导致账号被盗或密码泄露所产生的损失，本平台不承担责任。</p>
          <p>根据《互联网信息服务管理办法》等相关法律法规要求，<strong>平台保留在必要时要求用户绑定手机号或进行实名认证的权利</strong>。若用户拒绝配合，平台有权限制其使用部分或全部 AI 交互功能，恕不另行通知。</p>
          <p>用户注册时所填写的邮箱须真实有效。本平台可能通过该邮箱发送服务通知、简报订阅等重要信息，用户须承担因邮箱无效导致无法接收通知的风险。</p>
        </section>

        <!-- ── 联系方式 ── -->
        <section>
          <h2><span class="section-num">联系</span>版权投诉与合规联系</h2>
          <p>如涉及版权侵权投诉、内容下架申请、违规举报或商业合作咨询，请通过以下方式联系：</p>
          <div class="contact-block">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
            <a href="mailto:kaixxrua@gmail.com">kaixxrua@gmail.com</a>
          </div>
          <p class="mt-3 text-xs text-stone-400">本协议自 2026 年 3 月起生效。继续使用本平台即表示您已阅读、理解并接受本协议全部条款。</p>
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
  max-width: 760px;
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
.back-btn:hover { color: #44403c; }

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
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(168, 162, 158, 0.15);
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  background: #1c1917;
  color: white;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  flex-shrink: 0;
}

.legal-body section p {
  font-size: 14px;
  line-height: 1.75;
  color: #57534e;
  margin: 0 0 10px;
}
.legal-body section p:last-child { margin-bottom: 0; }

.legal-body ul {
  margin: 8px 0 10px;
  padding-left: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  list-style: none;
}

.legal-body ul li {
  font-size: 14px;
  line-height: 1.7;
  color: #57534e;
  padding-left: 18px;
  position: relative;
}
.legal-body ul li::before {
  content: '•';
  position: absolute;
  left: 4px;
  color: #a8a29e;
}

.legal-body strong { color: #292524; font-weight: 600; }

/* 警告高亮块 */
.highlight-block {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.highlight-block p { margin: 0 !important; font-size: 14px; line-height: 1.7; }

.highlight-block--warning {
  background: rgba(254, 243, 199, 0.5);
  border: 1px solid rgba(251, 191, 36, 0.3);
  color: #57534e;
}
.highlight-block--warning svg { color: #d97706; }

.warning-text {
  font-size: 13px !important;
  color: #78716c !important;
  background: rgba(254, 226, 226, 0.4);
  border: 1px solid rgba(252, 165, 165, 0.3);
  border-radius: 8px;
  padding: 10px 14px;
  margin-top: 4px !important;
}

.inline-link {
  color: #44403c;
  font-weight: 500;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.inline-link:hover { color: #1c1917; }

.mt-3 { margin-top: 12px; }

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
.contact-block a:hover { text-decoration: underline; }
</style>
