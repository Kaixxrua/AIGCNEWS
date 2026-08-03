from __future__ import annotations

"""huggingface embedding 休眠链路的依赖兼容性冒烟测试。

历史事故：sentence-transformers 2.2.2 在模块顶层
`from huggingface_hub import cached_download`，而该符号在
huggingface_hub 0.36 中已移除——任何一次 import sentence_transformers
都直接 ImportError。生产 EMBEDDING_PROVIDER=openai 不走这条路，
故障因此长期潜伏。此处用真实导入把"st/hf_hub/transformers 三角兼容"
钉在 CI 上，版本漂移时立即报警。
"""


def test_sentence_transformers_importable_with_pinned_hf_hub() -> None:
    import huggingface_hub
    import sentence_transformers
    import transformers

    # cached_download 类顶层符号缺失会在 import 时直接爆炸；
    # 走到这里即证明三者互相兼容。
    assert sentence_transformers.__version__
    assert transformers.__version__
    assert huggingface_hub.__version__


def test_langchain_huggingface_embeddings_importable() -> None:
    from langchain_huggingface import HuggingFaceEmbeddings

    assert HuggingFaceEmbeddings is not None
