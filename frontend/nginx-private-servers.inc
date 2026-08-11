# 私有 server 块挂载点（开源版为空占位）。
#
# 本文件在 http 上下文被 conf.d/default.conf 末尾 include。
# 私有部署经 compose overlay 将真实文件 bind-mount 覆盖到本路径，
# 承载姊妹产品/内部服务 vhost（例如价格站、LLM 中转反代）。
# 注意：文件必须存在（哪怕是空注释），缺失会导致 nginx 启动失败；
# 镜像已通过 Dockerfile COPY 内置本占位文件。
