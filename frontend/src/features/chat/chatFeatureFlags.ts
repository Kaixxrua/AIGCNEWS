/**
 * Chat 服务总开关（kill-switch）。
 *
 * 后端会话服务维护期间置为 false：
 * - ChatView 展示「服务暂不可用」遮罩，并跳过会话初始化；
 * - 论文页截图追问入口静默关闭。
 * 服务恢复后改回 true 即可，两处共用此唯一条件。
 */
export const CHAT_SERVICE_ENABLED = false
