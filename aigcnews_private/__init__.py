"""AIGCNEWS 私有源插件包。

承载不开源的采集实现（X 传输层）。公共仓库经
``backend.app.services.source_plugins.loader`` 按特性开关加载本包；
部署经 overlay 注入 PYTHONPATH（见 deploy/docker-compose.private.yml
与 README.md）。
"""
