// Domain labels used by the briefing prompts. Older English issues can retain
// these Chinese labels, so localize them when displaying the report.
const ENGLISH_TAGS: Record<string, string> = {
  '多模态': 'Multimodal',
  '代码生成': 'Code Generation',
  '图像生成': 'Image Generation',
  '视频生成': 'Video Generation',
  '语音合成': 'Speech Synthesis',
  '强化学习': 'Reinforcement Learning',
  '数据集': 'Datasets',
  '评测基准': 'Benchmarks',
  '推理优化': 'Inference Optimization',
  '模型压缩': 'Model Compression',
  '开源模型': 'Open Models',
  '商业化': 'Commercialization',
  '安全对齐': 'Safety & Alignment',
  '具身智能': 'Embodied AI',
  '知识图谱': 'Knowledge Graphs',
  'AI基础设施': 'AI Infrastructure',
  '数据工程': 'Data Engineering',
  'Web框架': 'Web Frameworks',
  'CLI工具': 'CLI Tools',
  '前端': 'Frontend',
  '融资收购': 'Funding & Acquisitions',
  '监管政策': 'Regulation',
  '芯片算力': 'Chips & Compute',
  '云服务': 'Cloud Services',
  '自动驾驶': 'Autonomous Driving',
  '医疗AI': 'Healthcare AI',
  '教育AI': 'Education AI',
  '企业AI': 'Enterprise AI',
  '开源生态': 'Open Source Ecosystem',
  'AI写作': 'AI Writing',
  'AI设计': 'AI Design',
  'AI编程': 'AI Coding',
  'AI营销': 'AI Marketing',
  '效率工具': 'Productivity',
  '开发者工具': 'Developer Tools',
  '个人助理': 'Personal Assistants',
  '协作工具': 'Collaboration',
  '数据分析': 'Data Analysis',
  '自动化': 'Automation',
  'API服务': 'API Services',
  '开源争议': 'Open Source Debates',
  '隐私安全': 'Privacy & Security',
  '编程语言': 'Programming Languages',
  '系统架构': 'System Architecture',
  '创业': 'Startups',
  '职业发展': 'Careers',
  '硬件': 'Hardware',
  'Web技术': 'Web Technologies',
  '分布式系统': 'Distributed Systems',
  '技术文化': 'Tech Culture',
  '产品发布': 'Product Launches',
  '行业动态': 'Industry News',
  '其他': 'Other',
  '研究论文': 'Research Papers',
  '观点争议': 'Debates',
}

/** Localize known heading chips in sanitized report HTML; keep prose and code intact. */
export function localizeReportHeadingTags(html: string, locale: string): string {
  if (!locale.toLowerCase().startsWith('en')) return html
  return html.replace(/<h[1-6]\b[^>]*>[\s\S]*?<\/h[1-6]>/g, (heading) =>
    heading.replace(/<code>(#?)([^<]*)<\/code>/g, (chip, hash: string, tag: string) => {
      const translated = Object.prototype.hasOwnProperty.call(ENGLISH_TAGS, tag) ? ENGLISH_TAGS[tag] : undefined
      return translated ? `<code>${hash}${translated.replace(/&/g, '&amp;')}</code>` : chip
    }),
  )
}
