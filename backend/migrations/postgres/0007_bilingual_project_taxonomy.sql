ALTER TABLE github_repo_enrichments
    ADD COLUMN category_name_zh VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN category_name_en VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN subcategory_name_zh VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN subcategory_name_en VARCHAR(128) NOT NULL DEFAULT '';

ALTER TABLE tool_website_enrichments
    ADD COLUMN category_name_zh VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN category_name_en VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN subcategory_name_zh VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN subcategory_name_en VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN description_en VARCHAR(512) NOT NULL DEFAULT '';

ALTER TABLE user_tool_website_overrides
    ADD COLUMN category_name_zh VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN category_name_en VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN subcategory_name_zh VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN subcategory_name_en VARCHAR(128) NOT NULL DEFAULT '',
    ADD COLUMN description_en VARCHAR(512) NOT NULL DEFAULT '';

CREATE TEMPORARY TABLE project_taxonomy_en_labels (
    slug VARCHAR(64) PRIMARY KEY,
    name_en VARCHAR(128) NOT NULL
) ON COMMIT DROP;

INSERT INTO project_taxonomy_en_labels (slug, name_en) VALUES
    ('productivity_tools', 'AI Productivity Tools'),
    ('writing_docs', 'Writing / Documents'),
    ('meetings_email', 'Meetings / Email'),
    ('browser_search', 'Browser / Search'),
    ('office_automation', 'Office Automation'),
    ('notes_knowledge', 'Notes / Knowledge Management'),
    ('personal_assistant', 'Personal Assistant'),
    ('spreadsheet_analysis', 'Spreadsheets / Data Analysis'),
    ('productivity_other', 'Other Productivity Tools'),
    ('coding_tools', 'AI Coding Tools'),
    ('code_generation', 'Code Generation'),
    ('code_review', 'Code Review'),
    ('ide_plugins', 'IDE / Editor Plugins'),
    ('testing_ci', 'Testing / CI Automation'),
    ('dev_agents', 'Development Agents'),
    ('code_search_docs', 'Code Search / Documentation'),
    ('low_code_scaffold', 'Low-Code / Scaffolding'),
    ('coding_other', 'Other Coding Tools'),
    ('agents_automation', 'AI Agents / Automation'),
    ('agent_frameworks', 'Agent Frameworks'),
    ('multi_agent', 'Multi-Agent Collaboration'),
    ('workflow_automation', 'Workflow Automation'),
    ('mcp_tool_use', 'MCP / Tool Use'),
    ('browser_rpa', 'Browser / RPA Automation'),
    ('research_agents', 'Research Agents'),
    ('personal_automation', 'Personal Automation'),
    ('agent_other', 'Other Agent Tools'),
    ('ai_apps', 'AI Products / Applications'),
    ('chat_clients', 'Chat Clients'),
    ('ai_search_products', 'AI Search Products'),
    ('vertical_saas', 'Vertical SaaS'),
    ('desktop_mobile_apps', 'Desktop / Mobile Apps'),
    ('marketing_sales', 'Marketing / Sales'),
    ('education_apps', 'Education Apps'),
    ('customer_ops', 'Customer Service / Operations'),
    ('ai_apps_other', 'Other AI Applications'),
    ('learning_resources', 'AI Tutorials / Learning Resources'),
    ('awesome_lists', 'Awesome Lists'),
    ('tutorials_courses', 'Tutorials / Courses'),
    ('prompt_collections', 'Prompt Collections'),
    ('papers_reading', 'Papers / Reading'),
    ('examples_templates', 'Examples / Templates'),
    ('newsletters_news', 'Newsletters / News'),
    ('project_collections', 'Project Collections'),
    ('learning_other', 'Other Learning Resources'),
    ('rag_knowledge', 'RAG / Knowledge Bases'),
    ('vector_search', 'Vector Search'),
    ('document_qa', 'Document Q&A'),
    ('graph_rag', 'GraphRAG'),
    ('enterprise_knowledge', 'Enterprise Knowledge Bases'),
    ('retrieval_infra', 'Retrieval Infrastructure'),
    ('ai_search_engine', 'AI Search Engines'),
    ('document_parsing', 'Document Parsing'),
    ('rag_other', 'Other Knowledge Tools'),
    ('multimodal_tools', 'Multimodal Tools'),
    ('image_generation', 'Image Generation'),
    ('video_generation', 'Video Generation'),
    ('speech_audio', 'Speech / Audio'),
    ('ocr_vision', 'OCR / Vision Understanding'),
    ('multimodal_chat', 'Multimodal Chat'),
    ('creative_design', 'Creative Design'),
    ('three_d_spatial', '3D / Spatial Content'),
    ('multimodal_other', 'Other Multimodal Tools'),
    ('models_infra', 'Models / Inference / Deployment'),
    ('local_llm_runtime', 'Local LLM Runtimes'),
    ('inference_serving', 'Inference Serving'),
    ('llm_gateway', 'LLM Gateways'),
    ('model_deploy_mlops', 'Model Deployment / MLOps'),
    ('model_compression_accel', 'Model Compression / Acceleration'),
    ('edge_runtime', 'Edge Runtimes'),
    ('model_management', 'Model Management'),
    ('models_infra_other', 'Other Model Infrastructure'),
    ('data_eval_training', 'Data / Evaluation / Training'),
    ('datasets', 'Datasets'),
    ('benchmark_eval', 'Benchmarks / Evaluation'),
    ('fine_tuning', 'Fine-Tuning'),
    ('synthetic_data', 'Synthetic Data'),
    ('training_frameworks', 'Training Frameworks'),
    ('observability', 'Observability'),
    ('data_labeling_cleaning', 'Data Labeling / Cleaning'),
    ('data_training_other', 'Other Data and Training Tools'),
    ('security_privacy', 'Security / Privacy'),
    ('prompt_security', 'Prompt Security'),
    ('privacy_local_first', 'Privacy / Local-First'),
    ('redteam_eval', 'Red Teaming / Security Evaluation'),
    ('compliance_guardrails', 'Compliance / Guardrails'),
    ('vulnerability_analysis', 'Vulnerability Analysis'),
    ('content_safety', 'Content Safety'),
    ('security_other', 'Other Security and Privacy Tools'),
    ('other', 'Other'),
    ('other_uncategorized', 'Uncategorized');

UPDATE github_repo_enrichments
SET category_name_zh = category_name,
    subcategory_name_zh = subcategory_name;
UPDATE github_repo_enrichments AS enrichment
SET category_name_en = label.name_en
FROM project_taxonomy_en_labels AS label
WHERE label.slug = enrichment.category_slug;
UPDATE github_repo_enrichments AS enrichment
SET subcategory_name_en = label.name_en
FROM project_taxonomy_en_labels AS label
WHERE label.slug = enrichment.subcategory_slug;

UPDATE tool_website_enrichments
SET category_name_zh = category_name,
    subcategory_name_zh = subcategory_name;
UPDATE tool_website_enrichments AS enrichment
SET category_name_en = label.name_en
FROM project_taxonomy_en_labels AS label
WHERE label.slug = enrichment.category_slug;
UPDATE tool_website_enrichments AS enrichment
SET subcategory_name_en = label.name_en
FROM project_taxonomy_en_labels AS label
WHERE label.slug = enrichment.subcategory_slug;

UPDATE user_tool_website_overrides
SET category_name_zh = category_name,
    subcategory_name_zh = subcategory_name;
UPDATE user_tool_website_overrides AS override_row
SET category_name_en = label.name_en
FROM project_taxonomy_en_labels AS label
WHERE label.slug = override_row.category_slug;
UPDATE user_tool_website_overrides AS override_row
SET subcategory_name_en = label.name_en
FROM project_taxonomy_en_labels AS label
WHERE label.slug = override_row.subcategory_slug;
