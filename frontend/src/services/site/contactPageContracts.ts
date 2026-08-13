/** /api/site/contact-page wire 契约：站点联系合作页（字段缺失视为未设置） */
export interface ContactPageServiceCardWire {
  title?: string | null
  description?: string | null
  icon?: string | null
}

export interface ContactPageEntryWire {
  label?: string | null
  value?: string | null
  href?: string | null
  qr_image_url?: string | null
}

export interface ContactPageWireResponse {
  enabled?: boolean | null
  nav_label?: string | null
  title?: string | null
  subtitle?: string | null
  service_cards?: ContactPageServiceCardWire[] | null
  contact_entries?: ContactPageEntryWire[] | null
  body_markdown?: string | null
  updated_at?: string | null
}
