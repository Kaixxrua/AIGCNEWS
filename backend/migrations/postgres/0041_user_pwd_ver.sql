-- 口令版本号：JWT 撤销语义的服务端锚点（渗透审计 AUTH-B）。
-- 原实现 JWT 7 天有效期内无法因改密而失效：改密后旧 token 照常可用。
-- login 签发时把 users.pwd_ver 写入 JWT 声明，RequireUser 每请求比对
-- 库内值；update_user_password 同事务 +1，旧 token 在下一个请求即 401。
-- 历史 JWT 无 pwd_ver 声明，升级后一律按失效处理（强制重新登录一次）。
-- 幂等（IF NOT EXISTS）：允许运维在统一 apply 前先手工补列以配合代码热重启，
-- 后续 runner 正式 apply 时重放为空操作再登记台账（与 0034 link_card 同先例）。
ALTER TABLE users ADD COLUMN IF NOT EXISTS pwd_ver INTEGER NOT NULL DEFAULT 1;
