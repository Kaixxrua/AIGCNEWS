# 主 server 内私有指令挂载点（开源版为空占位）。
#
# 本文件在 aigcnews.cn 主 server 块内被 include。
# 典型内容：真实客户端 IP 还原（set_real_ip_from / real_ip_header）——
# 当公网流量经 Tunnel/VPN 回源时，需要把回源地址加入白名单，
# 才能从边缘注入的 Header 还原真实客户端 IP。本地直连部署无需配置。
# 私有部署经 compose overlay 将真实文件 bind-mount 覆盖到本路径。
