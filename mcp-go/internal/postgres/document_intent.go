package postgres

// document_intent.go 移植 backend/app/domain/document_search_intent.py：
// 自然语言提问的时间窗口识别 + 问句外壳剥离。
//
// 对齐要点：
//   - 所有跨度按 rune 计（对齐 Python 的码点下标）；匹配在 ASCII 小写副本上做，
//     逐 rune 等长，跨度可直接回写原串。
//   - 纯 ASCII 短语两侧不得紧贴 ASCII 字母数字；中文短语子串匹配。
//   - 数字相对时间用 regexp（RE2 leftmost-first 与 Python re 在这两条无前瞻
//     的模式上同语义），字节偏移转 rune 偏移后再回写。
//   - 共享向量 backend/tests/fixtures/document_search_intent_vectors.json 双向钉住。

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type timePhrase struct {
	phrase string
	kind   string
}

var documentTimePhrases = []timePhrase{
	{"今天", "today"}, {"今日", "today"}, {"今早", "today"}, {"今晨", "today"},
	{"今晚", "today"}, {"今夜", "today"}, {"今儿", "today"}, {"刚刚", "today"},
	{"刚才", "today"}, {"today", "today"}, {"tonight", "today"},
	{"this morning", "today"},
	{"昨天", "yesterday"}, {"昨日", "yesterday"}, {"昨晚", "yesterday"},
	{"昨夜", "yesterday"}, {"昨儿", "yesterday"}, {"yesterday", "yesterday"},
	{"last night", "yesterday"},
	{"前天", "day_before_yesterday"}, {"前日", "day_before_yesterday"},
	{"前晚", "day_before_yesterday"},
	{"最近", "recent"}, {"近期", "recent"}, {"近日", "recent"}, {"最新", "recent"},
	{"这几天", "recent"}, {"这两天", "recent"}, {"近几天", "recent"}, {"近来", "recent"},
	{"recently", "recent"}, {"recent", "recent"}, {"latest", "recent"},
	{"lately", "recent"}, {"past week", "recent"},
	{"本周", "this_week"}, {"这周", "this_week"}, {"这一周", "this_week"},
	{"这个星期", "this_week"}, {"本星期", "this_week"}, {"这星期", "this_week"},
	{"this week", "this_week"},
	{"上周", "last_week"}, {"上星期", "last_week"}, {"上个星期", "last_week"},
	{"上一周", "last_week"}, {"last week", "last_week"},
	{"本月", "this_month"}, {"这个月", "this_month"}, {"这月", "this_month"},
	{"this month", "this_month"},
	{"上个月", "last_month"}, {"上月", "last_month"}, {"last month", "last_month"},
}

var (
	zhRelativeRE = regexp.MustCompile(
		`(最近|过去|近|前)? ?([0-9]+|[一二两三四五六七八九十]+) ?个? ?` +
			`(小时|天|日|周|星期|礼拜|月)(之内|以内|以来|内|里)?`)
	enRelativeRE = regexp.MustCompile(`(past|last|previous) ([0-9]+) (hours|hour|days|day|weeks|week|months|month)`)
)

var documentAskTriggers = []string{
	"什么", "哪些", "啥", "总结", "概括", "汇总", "盘点", "梳理", "介绍",
	"有没有", "讲讲", "说说", "告诉我", "请问",
	"what", "which", "summarize", "summarise", "summary", "tell me", "any news",
}

var documentAskFillers = []string{
	"简洁地", "简洁", "简要", "简单", "一下", "请问", "请", "告诉我", "给我", "帮忙",
	"总结", "概括", "汇总", "盘点", "梳理", "介绍", "讲讲", "说说", "了解", "有没有",
	"发布会上", "发布会", "都发布了", "发布了", "发布", "推出了", "推出", "宣布了",
	"宣布", "上线了", "上线", "更新了", "更新", "开源了", "有什么", "有哪些", "有啥",
	"是什么", "什么", "哪些", "啥", "新闻", "消息", "资讯", "动态", "进展", "大事",
	"事情", "晚上", "早上", "上午", "下午", "凌晨", "夜里", "深夜", "半夜", "关于",
	"的", "了", "吗", "呢", "吧", "啊", "呀", "都", "和", "与", "及",
	"please", "summarize", "summarise", "summary of", "summary", "briefly", "brief",
	"concisely", "concise", "tell me about", "tell me", "what's new", "what is new",
	"what did", "what has", "what have", "what's", "what", "which", "any news",
	"news", "updates", "update", "released", "release", "announced",
	"announcements", "announcement", "announce", "launched", "launch", "shipped",
	"new", "the", "of", "from", "in", "on", "at", "by", "for", "is", "are", "was",
	"were", "has", "have", "did", "do", "does", "and", "about",
}

var zhDigits = map[string]int{"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

const (
	maxWindowDays = 365
	maxTimeCount  = 100000
)

// dateWindow 是 published_date 闭开区间 [since, until)，均为 YYYY-MM-DD。
type dateWindow struct {
	since string
	until string
}

type queryIntent struct {
	window    *dateWindow
	asks      bool
	remainder string // 剥掉时间短语后的查询（未剥问句外壳；空白已折叠）
}

func asciiLowerRunes(runes []rune) []rune {
	out := make([]rune, len(runes))
	for i, r := range runes {
		if r >= 'A' && r <= 'Z' {
			r += 'a' - 'A'
		}
		out[i] = r
	}
	return out
}

func isASCIIString(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] >= utf8.RuneSelf {
			return false
		}
	}
	return true
}

// boundedASCII：ASCII 短语两侧不得紧贴 ASCII 字母数字（短语首尾均为字母）。
func boundedASCII(text []rune, start, end int) bool {
	if start > 0 && isASCIIAlnum(text[start-1]) {
		return false
	}
	return !(end < len(text) && isASCIIAlnum(text[end]))
}

// findPhrase 返回 phrase 在 lowered 中的非重叠命中起点（左到右）。
func findPhrase(lowered []rune, phrase string) []int {
	pRunes := []rune(phrase)
	asciiPhrase := isASCIIString(phrase)
	var hits []int
	for i := 0; i+len(pRunes) <= len(lowered); {
		if !runesEqual(lowered[i:i+len(pRunes)], pRunes) {
			i++
			continue
		}
		end := i + len(pRunes)
		if !asciiPhrase || boundedASCII(lowered, i, end) {
			hits = append(hits, i)
			i = end
		} else {
			i++
		}
	}
	return hits
}

func runesEqual(a, b []rune) bool {
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func containsPhrase(lowered []rune, phrase string) bool {
	return len(findPhrase(lowered, phrase)) > 0
}

func blankRunes(text []rune, start, end int) {
	for i := start; i < end; i++ {
		text[i] = ' '
	}
}

// byLengthDesc 对齐 sorted(phrases, key=len, reverse=True)：按 rune 数降序、稳定。
func byLengthDesc(phrases []string) []string {
	sorted := append([]string(nil), phrases...)
	sort.SliceStable(sorted, func(i, j int) bool {
		return utf8.RuneCountInString(sorted[i]) > utf8.RuneCountInString(sorted[j])
	})
	return sorted
}

var (
	askFillersByLength  = byLengthDesc(documentAskFillers)
	timePhrasesByLength = func() []timePhrase {
		sorted := append([]timePhrase(nil), documentTimePhrases...)
		sort.SliceStable(sorted, func(i, j int) bool {
			return utf8.RuneCountInString(sorted[i].phrase) > utf8.RuneCountInString(sorted[j].phrase)
		})
		return sorted
	}()
)

// stripAskFillers 把问句外壳短语替换为等长空白。
func stripAskFillers(text string) string {
	runes := []rune(text)
	lowered := asciiLowerRunes(runes)
	for _, phrase := range askFillersByLength {
		n := utf8.RuneCountInString(phrase)
		for _, index := range findPhrase(lowered, phrase) {
			blankRunes(runes, index, index+n)
			blankRunes(lowered, index, index+n)
		}
	}
	return string(runes)
}

func zhNumber(raw string) int {
	if raw != "" && strings.Trim(raw, "0123456789") == "" {
		n, err := strconv.Atoi(raw)
		if err != nil { // 溢出：Python int 无上限，随后同样被夹到 maxTimeCount
			return maxTimeCount
		}
		return n
	}
	if head, tail, ok := strings.Cut(raw, "十"); ok {
		tens := 1
		if head != "" {
			tens = zhDigits[head]
		}
		ones := 0
		if tail != "" {
			ones = zhDigits[tail]
		}
		return tens*10 + ones
	}
	if utf8.RuneCountInString(raw) == 1 {
		return zhDigits[raw]
	}
	return 0
}

func unitDays(count int, unit string) int {
	switch unit {
	case "小时", "hour", "hours":
		days := (count + 23) / 24
		if days < 1 {
			days = 1
		}
		return days
	case "周", "星期", "礼拜", "week", "weeks":
		return count * 7
	case "月", "month", "months":
		return count * 30
	}
	return count
}

func civilDate(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

func newDateWindow(since, untilInclusive time.Time) *dateWindow {
	return &dateWindow{since: since.Format("2006-01-02"), until: untilInclusive.AddDate(0, 0, 1).Format("2006-01-02")}
}

func kindWindow(kind string, today time.Time) *dateWindow {
	day := func(n int) time.Time { return today.AddDate(0, 0, n) }
	monday := day(-((int(today.Weekday()) + 6) % 7))
	first := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC)
	switch kind {
	case "today", "yesterday":
		// 昨晚的海外发布多落在上海日界两侧；今天的 PT/UTC 源条目常标成昨天。
		return newDateWindow(day(-1), today)
	case "day_before_yesterday":
		return newDateWindow(day(-2), day(-1))
	case "recent":
		return newDateWindow(day(-7), today)
	case "this_week":
		return newDateWindow(monday.AddDate(0, 0, -1), today)
	case "last_week":
		return newDateWindow(monday.AddDate(0, 0, -8), monday.AddDate(0, 0, -1))
	case "this_month":
		return newDateWindow(first.AddDate(0, 0, -1), today)
	}
	// last_month
	lastOfPrevious := first.AddDate(0, 0, -1)
	previousFirst := time.Date(lastOfPrevious.Year(), lastOfPrevious.Month(), 1, 0, 0, 0, 0, time.UTC)
	return newDateWindow(previousFirst.AddDate(0, 0, -1), lastOfPrevious)
}

func daysWindow(days int, today time.Time) *dateWindow {
	if days > maxWindowDays {
		days = maxWindowDays
	}
	if days < 1 {
		days = 1
	}
	return newDateWindow(today.AddDate(0, 0, -days), today)
}

type windowMatch struct {
	position int
	window   *dateWindow
}

// runeOffset 把字节偏移转成 rune 偏移。
func runeOffset(s string, byteOffset int) int {
	return utf8.RuneCountInString(s[:byteOffset])
}

// parseQueryIntent 复刻 parse_query_intent；normalized 须已 NFKC + 空白折叠，
// today 为调度时区自然日。窗口取查询中最靠前的时间表达（同位按登记序）。
func parseQueryIntent(normalized string, today time.Time) queryIntent {
	today = civilDate(today)
	text := []rune(normalized)
	lowered := asciiLowerRunes(text)
	var matches []windowMatch

	loweredString := string(lowered)
	for _, m := range zhRelativeRE.FindAllStringSubmatchIndex(loweredString, -1) {
		start, end := runeOffset(loweredString, m[0]), runeOffset(loweredString, m[1])
		group := func(i int) string {
			if m[2*i] < 0 {
				return ""
			}
			return loweredString[m[2*i]:m[2*i+1]]
		}
		prefix, rawCount, unit, suffix := group(1), group(2), group(3), group(4)
		count := min(zhNumber(rawCount), maxTimeCount)
		if (prefix == "" && suffix == "") || count <= 0 {
			continue
		}
		// 无前缀时数字不得是 ASCII 词尾（llama3个月内 的 3 属于型号）。
		if prefix == "" && start > 0 && isASCIIAlnum(lowered[start-1]) {
			continue
		}
		matches = append(matches, windowMatch{start, daysWindow(unitDays(count, unit), today)})
		blankRunes(text, start, end)
	}
	lowered = asciiLowerRunes(text)
	loweredString = string(lowered)
	for _, m := range enRelativeRE.FindAllStringSubmatchIndex(loweredString, -1) {
		start, end := runeOffset(loweredString, m[0]), runeOffset(loweredString, m[1])
		if !boundedASCII(lowered, start, end) {
			continue
		}
		count, err := strconv.Atoi(loweredString[m[4]:m[5]])
		if err != nil {
			count = maxTimeCount
		}
		count = min(count, maxTimeCount)
		if count <= 0 {
			continue
		}
		matches = append(matches, windowMatch{start, daysWindow(unitDays(count, loweredString[m[6]:m[7]]), today)})
		blankRunes(text, start, end)
	}
	lowered = asciiLowerRunes(text)
	for _, entry := range timePhrasesByLength {
		n := utf8.RuneCountInString(entry.phrase)
		for _, index := range findPhrase(lowered, entry.phrase) {
			matches = append(matches, windowMatch{index, kindWindow(entry.kind, today)})
			blankRunes(text, index, index+n)
			blankRunes(lowered, index, index+n)
		}
	}

	var window *dateWindow
	best := -1
	for _, m := range matches {
		if best < 0 || m.position < best {
			best, window = m.position, m.window
		}
	}
	normalizedLowered := asciiLowerRunes([]rune(normalized))
	asks := false
	for _, trigger := range documentAskTriggers {
		if containsPhrase(normalizedLowered, trigger) {
			asks = true
			break
		}
	}
	return queryIntent{window: window, asks: asks, remainder: strings.Join(strings.Fields(string(text)), " ")}
}
