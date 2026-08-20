package postgres

// scan.go 是宽行 SELECT（列数多于消费方字段，如 rank snapshot 30 列 JOIN）
// 的公共扫描助手：先 any-slice 承接 pgx 原生解码，再按列位窄化到指针。
// NULL 经 any 得到 nil → 各 as* 助手统一回 nil（JSON null）。

// asString 窄化到 *string；非 string 形态（含 NULL）回 nil。
func asString(value any) *string {
	if value == nil {
		return nil
	}
	text, ok := value.(string)
	if !ok {
		return nil
	}
	return &text
}

// asFloat 窄化到 *float64（DOUBLE PRECISION 列经 pgx 得 float64）。
func asFloat(value any) *float64 {
	if value == nil {
		return nil
	}
	f, ok := value.(float64)
	if !ok {
		return nil
	}
	return &f
}

// asInt32 窄化到 *int32；pgx 对 INTEGER 给 int32、对 COUNT 给 int64，
// 统一收纳。
func asInt32(value any) *int32 {
	if value == nil {
		return nil
	}
	switch n := value.(type) {
	case int32:
		return &n
	case int:
		converted := int32(n)
		return &converted
	case int64:
		converted := int32(n)
		return &converted
	default:
		return nil
	}
}
