export interface AssessmentClaim {
  text_zh: string
  text_en: string
  source: 'readme' | 'description'
  quote: string
}

export interface ProjectAssessment {
  version: 1
  decision: 'evaluate' | 'insufficient' | 'out_of_scope'
  relevance: 'core' | 'adjacent' | 'unrelated' | 'unknown'
  relevance_evidence: AssessmentClaim | null
  audience: AssessmentClaim[]
  value: AssessmentClaim[]
  setup: AssessmentClaim[]
  limitations: AssessmentClaim[]
  assessed_at: string
  readme_sha256: string
  license_spdx_id: string
}
