package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"path"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Separate queries keep GitHub's five-operator limit and do not OR qualifiers:
// GitHub only supports OR between search words, not between topic: qualifiers.
var discoveryQueries = []string{
	automaticGameQuery,
	`"game port" OR "native port" OR demake OR "game clone" OR "game engine" OR "open source game"`,
	`topic:game`,
}

const maxDiscoveryPage = 100000
const discoveryReadmeBytes = 64 << 10

type discoveryRange struct {
	Min int `json:"min"`
	Max int `json:"max"`
}

type discoveryCursor struct {
	Version int              `json:"v"`
	Query   int              `json:"q"`
	Page    int              `json:"p"`
	Next    int              `json:"next"`
	Bounds  discoveryRange   `json:"bounds"`
	Ranges  []discoveryRange `json:"ranges"`
}

func discoveryBounds(bounds starBounds) discoveryRange {
	r := discoveryRange{Max: 1_000_000_000}
	if bounds.min != nil {
		r.Min = *bounds.min
	}
	if bounds.max != nil {
		r.Max = *bounds.max
	}
	return r
}

func parseDiscoveryCursor(raw string, bounds starBounds, page int) (discoveryCursor, error) {
	r := discoveryBounds(bounds)
	c := discoveryCursor{Version: 1, Page: page, Next: page, Bounds: r, Ranges: []discoveryRange{r}}
	invalid := errors.New("发现进度无效，请重新按 Stars 查找")
	if raw == "" {
		if page < 1 || page > 10 {
			return c, invalid
		}
		return c, nil
	}
	if len(raw) > 4096 || page < 2 || page > maxDiscoveryPage {
		return c, invalid
	}
	b, err := base64.RawURLEncoding.DecodeString(raw)
	if err != nil || json.Unmarshal(b, &c) != nil || c.Version != 1 || c.Query < 0 || c.Query >= len(discoveryQueries) || c.Page < 1 || c.Page > 10 || c.Next != page || c.Bounds != r || len(c.Ranges) < 1 || len(c.Ranges) > 32 {
		return c, invalid
	}
	for i, part := range c.Ranges {
		if part.Min < r.Min || part.Max > r.Max || part.Min > part.Max || i > 0 && part.Max >= c.Ranges[i-1].Min {
			return c, invalid
		}
	}
	return c, nil
}

func encodeDiscoveryCursor(c discoveryCursor) string {
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}

// Each call makes one bounded search request. Overfull ranges are split before
// reading later pages, so low-star games do not disappear behind the top 1,000.
// The cursor is self-contained for restarts; it can only select these queries.
func (g *GitHub) discoverNext(ctx context.Context, bounds starBounds, page int, raw string) (DiscoveryPage, error) {
	return g.discoverPage(ctx, bounds, page, raw, false)
}

func (g *GitHub) discoverAutomatic(ctx context.Context, bounds starBounds, page int, raw string) (DiscoveryPage, error) {
	return g.discoverPage(ctx, bounds, page, raw, true)
}

func (g *GitHub) discoverPage(ctx context.Context, bounds starBounds, page int, raw string, advancePending bool) (DiscoveryPage, error) {
	c, err := parseDiscoveryCursor(raw, bounds, page)
	if err != nil {
		return DiscoveryPage{}, err
	}
	part := c.Ranges[0]
	queryBounds := starBounds{min: &part.Min, max: &part.Max}
	result, err := g.searchPage(ctx, discoveryQueries[c.Query]+" fork:true", queryBounds, 100, c.Page)
	if err != nil {
		return DiscoveryPage{}, err
	}
	evidenceErr := g.resolveGameEvidence(ctx, result.Items)
	games, err := filterSearchGames(result.Items, bounds, true)
	if err != nil {
		return DiscoveryPage{}, err
	}
	response := DiscoveryPage{Items: games, Page: page, TotalCandidates: result.Total, Incomplete: result.Incomplete}
	if evidenceErr != nil {
		// Keep confirmed games visible while preserving this exact position.
		// Successful README evidence is cached, so retries only fill gaps.
		response.EvidencePending, response.Warning = true, evidenceErr.Error()
		if !advancePending {
			response.HasMore, response.NextPage, response.NextCursor = true, page, raw
			return response, nil
		}
		response.Warning += "；本轮继续后续候选，未核实项目将在下一轮重新查询。"
	}
	if result.Total > 1000 && part.Min < part.Max {
		// The largest observed star count avoids empty splits of the initial
		// billion-star upper bound; preserve the requested bound in the cursor.
		upper := part.Max
		if len(result.Items) > 0 && result.Items[0].Stars >= part.Min && result.Items[0].Stars < upper {
			upper = result.Items[0].Stars
		}
		if upper > part.Min {
			middle := part.Min + (upper-part.Min)/2
			c.Ranges = append([]discoveryRange{{Min: middle + 1, Max: part.Max}, {Min: part.Min, Max: middle}}, c.Ranges[1:]...)
			c.Page = 1
		} else {
			// More than 1,000 repositories can share the same Stars value.
			// Search that exact value next, then report the remaining API cap.
			c.Ranges[0].Max, c.Page = part.Min, 1
		}
	} else if c.Page < 10 && c.Page*100 < result.Total {
		c.Page++
	} else {
		response.LimitReached = result.Total > 1000
		c.Ranges, c.Page = c.Ranges[1:], 1
		if len(c.Ranges) == 0 {
			c.Query++
			c.Ranges = []discoveryRange{c.Bounds}
		}
	}
	response.HasMore = c.Query < len(discoveryQueries) && page < maxDiscoveryPage
	if response.HasMore {
		c.Next = page + 1
		response.NextPage, response.NextCursor = c.Next, encodeDiscoveryCursor(c)
	} else if c.Query < len(discoveryQueries) {
		response.LimitReached = true
	}
	return response, nil
}

var camelWordBoundary = regexp.MustCompile(`([a-z0-9])([A-Z])`)
var acronymWordBoundary = regexp.MustCompile(`([A-Z])([A-Z][a-z])`)
var toolIdentityMarker = regexp.MustCompile(`(?i)(^|[-_ ])(sdk|toolkit|emulator|emulators|framework|tutorials?|examples?|course|cheats?|trainer)([-_ ]|$)`)
var toolRoleMarker = regexp.MustCompile(`(?i)\b(sdk|toolkit|emulators?|development[ -]kit|runtime librar(?:y|ies)|static recompiler|game (?:server management|hosting|development (?:framework|library)|editor|speed modifier|launcher|backend)|network client|tracing|diagnostics|reporting services|reportviewer|image editor|datepicker)\b`)
var launcherRoleMarker = regexp.MustCompile(`(?i)^\s*(?:(?:[a-z0-9_-]+\s+)?launchers?\b|(?:an?|the)\s+(?:[a-z-]+\s+){0,4}launcher\b)`)
var mentionedToolClause = regexp.MustCompile(`(?i)\b(?:uses|using|utili[sz]es|built with|requires?|based on)\s+[^.!;\n]*\b(?:sdk|toolkit|framework|emulator|engine|library)\b[^.!;\n]*`)
var negatedToolClause = regexp.MustCompile(`(?i)\b(?:no|without|not an?|is not an?|isn't an?|does not include|doesn't include)\b[^.!;\n]*\b(?:sdk|emulator|recompilation|toolkit)\b[^.!;\n]*`)
var componentRoleMarker = regexp.MustCompile(`(?i)\b(?:benchmark|asset pipeline|behaviou?r tree (?:solution|framework|library|editor)|action planner|(?:first[ -]person|third[ -]person|character) controller for|(?:kcp|tcp|icmp|network) tunnel|tunnel for games|quickstart|standard (?:c\+\+ )?library|c\+\+ interface|game coding agent|game development.*book)\b`)
var utilityRoleMarker = regexp.MustCompile(`(?i)\b(?:game (?:creator|creation tool|performance optimi[sz]ation service)|search(?:es|ing)? [^.\n]{0,80}game install paths|minimal example)\b|(?:脚本|编译器)[^。\n]{0,30}(?:语法|引擎)内核`)
var readmeProjectRoleMarker = regexp.MustCompile(`(?im)(?:^|\n)\s*(?:(?:[a-z0-9_.*-]+[ \t]+){1,5}(?:is|provides)[ \t]+(?:(?:an?|the)[ \t]+)?|(?:an?|the)[ \t]+)(?:[a-z0-9_.*-]+\s+){0,7}(?:sdk|toolkit|toolset|emulator|framework|library|extension|plugin|component|behaviou?r tree solution)(?:\s+(?:for|to|that|with|in)\b|\s*[.:!\r]?(?:\n|$))|(?:^|\n)\s*[a-z0-9_.*-]*(?:游戏|客户端)开发(?:使用)?(?:框架|工具库|脚手架)`)
var componentTopicMarker = regexp.MustCompile(`(?i)(^|[-_ ])(library|libraries|template|templates|benchmark|benchmarks)([-_ ]|$)`)
var gamePortToolkitMarker = regexp.MustCompile(`(?i)\bporting toolkit for\b`)
var genericEngineMarker = regexp.MustCompile(`(?i)\b(?:(?:game|visual[ -]novel)[ -](?:client[ -])?engine|game development framework|game framework)\b`)
var generalConsoleMarker = regexp.MustCompile(`(?i)^(?:playstation ?[1-5]|ps[1-5]|xbox(?: 360)?|n64|nintendo 64) (?:games|titles)\b`)
var reimplementationMarker = regexp.MustCompile(`(?i)\b(?:re-?implement(?:ation|ed)?|remakes?|demakes?|recreations?|clones?|decompilations?|recompilations?|recompiled)\b`)
var specificRecompilationMarker = regexp.MustCompile(`(?i)\b(?:static )?(?:recompilation|decompilation)\s+(?:(?:project|runtime)\s+)?(?:of|for)\s+\S`)
var gameGenreMarker = regexp.MustCompile(`(?i)\b(?:fps|rts|rpg|roguelike|roguelite|metroidvania|platformer|shooter|arcade|adventure|fighting|4x|visual[ -]novel|racing[ -]game|puzzle[ -]game)\b`)
var gameReadmeMarker = regexp.MustCompile(`(?i)\b(?:games?|gameplay|playable|players?)\b|游戏|玩家|模拟器|角色扮演|回合制|平台跳跃`)

// Topics indicate the domain, not whether the repository is a playable game.
// A game object, game library or screenshot tool is not positive game evidence.
var playableGameMarker = regexp.MustCompile(`(?i)\b(?:playable(?: preview| demo| game)?|video[ -]game|(?:multi[ -]?player|single[ -]?player|strategy|simulation|puzzle|arcade|shooter|adventure|fighting|racing|survival|action|board|card|role[ -]?playing|real[ -]?time(?: strategy| tactics)?|open[ -]?world)(?: [a-z-]+){0,2} games?|gameplay|(?:an?|the|this) game (?:where|in which|about|is|was|written|built)|games? (?:written|built|made|about)|(?:play|playing|start|launch|beat|win|loading new) (?:your |the |this |original )?games?|(?:original|own)(?: copy of the)? game(?: files| data| assets)?)\b|(?:开源|冒险|策略|动作|角色扮演|回合制|平台跳跃|休闲|文字|益智|射击)(?:类|类的)?游戏|游戏(?:玩法|介绍)|玩家|模拟器`)
var describedGameMarker = regexp.MustCompile(`(?i)\bgames?[ \t]*(?:[—:–-]|with\b|in\b|for\b|written\b|built\b|made\b|where\b|about\b|available\b|remake\b|recompiled\b)`)
var declaredToolRoleMarker = regexp.MustCompile(`(?i)\b(?:framework|librar(?:y|ies)|toolset|extensions?|plugins?|bindings?|scaffold|mod[ -]manager|game[ -](?:updater|patcher)|(?:custom|heart[ -]rate)[ -]counter)\b|(?:开发|自动化)(?:使用)?(?:框架|脚手架|工具库)|网络库`)
var genericDevelopmentMarker = regexp.MustCompile(`(?i)\b(?:general[ -]purpose|(?:make|making|create|creating|develop|developing|build|building) [^.!;\n]{0,50}\bgames|game development framework|game development library)\b`)
var readmeCode = regexp.MustCompile("(?s)```.*?```|~~~.*?~~~|<!--.*?-->")
var readmeMarkup = regexp.MustCompile(`(?s)</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*|/?)>|https?://[^\s<>\)]+`)
var localizedReadmeLink = regexp.MustCompile(`(?i)\]\((?:\./)?(README[-_.](?:zh|cn)[A-Za-z0-9_.-]*\.(?:md|markdown|rst|txt))\)`)

// A declared component role wins over later examples or installation steps.
// An actual game that merely names its dependencies keeps its game identity.
func declaredToolProject(text string) bool {
	role := declaredToolRoleMarker.FindStringIndex(text)
	if role == nil {
		return false
	}
	for _, marker := range []*regexp.Regexp{playableGameMarker, describedGameMarker} {
		if game := marker.FindStringIndex(text); game != nil && game[0] < role[0] {
			return false
		}
	}
	return true
}

// Metadata is not required to contain the English word "game". Genres and
// game-specific ports are evidence too. General tools remain separate from
// playable projects; merely mentioning the SDK used/excluded is not a role.
func excludedGameCandidate(repo searchRepository) bool {
	name := acronymWordBoundary.ReplaceAllString(repo.Name+" "+path.Base(repo.FullName), "$1 $2")
	name = strings.ToLower(camelWordBoundary.ReplaceAllString(name, "$1 $2"))
	topics := strings.ToLower(strings.Join(repo.Topics, " "))
	description := normalizedPurpose(repo.Description)
	return strings.Contains(name, "awesome") || strings.Contains(topics, "awesome") || collectionNameMarker.MatchString(name+" "+topics) || toolIdentityMarker.MatchString(name) || (toolRoleMarker.MatchString(description) && !gamePortToolkitMarker.MatchString(description)) || componentRoleMarker.MatchString(description) || declaredToolProject(description) && !originalExtension.MatchString(description) || utilityRoleMarker.MatchString(description) || componentTopicMarker.MatchString(name) || genericDevelopmentMarker.MatchString(description) || launcherRoleMarker.MatchString(description) || generalConsoleMarker.MatchString(description) || collectionReadmePurpose.MatchString(description) || unrelatedPurpose.MatchString(description) || toolPurpose(description)
}

func metadataGameCandidate(repo searchRepository, knownGames map[string]bool) bool {
	if excludedGameCandidate(repo) {
		return false
	}
	if knownGames[strings.ToLower(repo.FullName)] {
		return true
	}
	description := normalizedPurpose(repo.Description)
	text := description + " " + strings.Join(repo.Topics, " ")
	if pluralImplementations.MatchString(description) || strings.Contains(strings.ToLower(description), "collection of games") || collectionDescriptionMarker.MatchString(description) || originalExtension.MatchString(description) {
		return false
	}
	if portMarker.MatchString(text) || specificRecompilationMarker.MatchString(description) || nativePortMarker.MatchString(description) && reimplementationMarker.MatchString(repo.Description) {
		return true
	}
	if genericEngineMarker.MatchString(description) {
		return false
	}
	if reimplementationMarker.MatchString(description) && (gameDescriptionMarker.MatchString(description) || gameGenreMarker.MatchString(text)) {
		return true
	}
	for _, topic := range repo.Topics {
		if (strings.EqualFold(topic, "game") || strings.HasSuffix(strings.ToLower(topic), "-game")) && reimplementationMarker.MatchString(description) {
			return true
		}
	}
	return namedGameVersion.MatchString(description) || primaryGameType(description) || primaryGameNoun.MatchString(description) || selfGameClaim.MatchString(description) || playableGameMarker.MatchString(description) || describedGameMarker.MatchString(description)
}

func isGameCandidate(repo searchRepository, knownGames map[string]bool) bool {
	if knownGames[strings.ToLower(repo.FullName)] {
		return true
	}
	if excludedGameCandidate(repo) {
		return false
	}
	if metadataGameCandidate(repo, knownGames) {
		return true
	}
	text := discoveryReadmeText(repo.Readme)
	intro := discoveryReadmeIntro(text)
	identity := normalizedPurpose(intro)
	// A single-game native port may include its translator and tooling. Its
	// explicit runtime and original-copy requirements establish the purpose.
	if gamePortToolkitMarker.MatchString(repo.Description) && nativeRuntimeEvidence.MatchString(identity) && playableGameMarker.MatchString(identity) {
		return true
	}
	if collectionReadmePurpose.MatchString(identity) || readmeProjectRoleMarker.MatchString(identity) || toolPurpose(identity) {
		return false
	}
	if !genericEngineMarker.MatchString(identity) && (primaryGameType(identity) || selfGameClaim.MatchString(identity) || describedGameMarker.MatchString(identity)) {
		return true
	}
	if genericEngineMarker.MatchString(normalizedPurpose(repo.Description)) || genericEngineMarker.MatchString(identity) {
		return dedicatedEnginePurpose(repo, identity, text)
	}
	return directRecompiledRuntime.MatchString(identity) || gamePlayControls.MatchString(identity) || playOwnProject(repo, identity) || engineWord.MatchString(repo.Description) && supportedGameReleases.MatchString(identity) || playableEngine.MatchString(identity) || targetClientPurpose(repo, identity, text) || reconstructsGameEngine(repo) || likeTheGame.MatchString(identity) || namedGameVersion.MatchString(identity) || reversedGame.MatchString(identity) || explicitGameRuntime.MatchString(identity) && gameDomain(repo) || primaryGameType(identity) || primaryGameNoun.MatchString(identity) || selfGameClaim.MatchString(identity) || playableGameMarker.MatchString(identity) || describedGameMarker.MatchString(identity) || gameDomain(repo) && (gameSubjectPort.MatchString(identity) || namedGamePorting(repo, identity)) || purposeRecreation.MatchString(identity) && gameDescriptionMarker.MatchString(text)
}

type discoveryReadme struct {
	Text string
	At   time.Time
}

func (g *GitHub) readGameEvidence(ctx context.Context, repo string) (string, error) {
	key := strings.ToLower(repo)
	g.mu.RLock()
	cached, ok := g.discoveryReadmes[key]
	g.mu.RUnlock()
	if ok && time.Since(cached.At) < 24*time.Hour {
		return cached.Text, nil
	}
	readmePath := "README.md"
	read := func(endpoint string) (string, error) {
		var file struct {
			Path     string `json:"path"`
			Encoding string `json:"encoding"`
			Content  string `json:"content"`
			Size     int    `json:"size"`
		}
		if err := g.get(ctx, endpoint, &file); err != nil {
			var failure *githubError
			if errors.As(err, &failure) && failure.Status == 404 {
				return "", nil
			}
			return "", err
		}
		if file.Size < 0 || file.Size > 1<<20 || len(file.Content) > 2<<20 {
			return "", nil
		}
		if file.Encoding != "base64" {
			return "", errors.New("GitHub README 编码无效，请稍后重试核验")
		}
		body, err := io.ReadAll(io.LimitReader(base64.NewDecoder(base64.StdEncoding, strings.NewReader(file.Content)), discoveryReadmeBytes))
		if err != nil {
			return "", errors.New("GitHub README 内容无法解码，请稍后重试核验")
		}
		if file.Path != "" && !strings.ContainsAny(file.Path, "?#\\") && !strings.HasPrefix(file.Path, "/") && !strings.Contains(file.Path, "..") {
			readmePath = file.Path
		}
		return string(body), nil
	}
	text, err := read("/repos/" + repo + "/readme")
	if err != nil {
		return "", err
	}
	// Only follow one actual, same-repository README language link. Never
	// request arbitrary URLs mentioned in untrusted repository documents.
	if link := localizedReadmeLink.FindStringSubmatch(text); len(link) > 1 && !gameReadmeMarker.MatchString(text) {
		translated, err := read("/repos/" + repo + "/contents/" + url.PathEscape(path.Join(path.Dir(readmePath), link[1])))
		if err != nil {
			return "", err
		}
		text += "\n" + translated
	}
	g.mu.Lock()
	if g.discoveryReadmes == nil || len(g.discoveryReadmes) >= 2000 {
		g.discoveryReadmes = map[string]discoveryReadme{}
	}
	g.discoveryReadmes[key] = discoveryReadme{Text: text, At: time.Now()}
	g.mu.Unlock()
	return text, nil
}

func (g *GitHub) resolveGameEvidence(ctx context.Context, items []searchRepository) error {
	catalog, err := readCatalog()
	if err != nil {
		return err
	}
	known := map[string]bool{}
	for _, game := range catalog {
		known[strings.ToLower(game.Repo)] = true
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	var wg sync.WaitGroup
	var mu sync.Mutex
	var firstError error
	work := make(chan int)
	for worker := 0; worker < 4; worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for index := range work {
				if ctx.Err() != nil {
					return
				}
				text, err := g.readGameEvidence(ctx, items[index].FullName)
				if err != nil {
					mu.Lock()
					if firstError == nil {
						firstError = fmt.Errorf("游戏候选的 README 核对未完成，可重试本页：%w", err)
					}
					mu.Unlock()
					var failure *githubError
					if errors.As(err, &failure) && (failure.Status == 403 || failure.Status == 429) {
						// Do not spend the rest of the page repeating a known rate
						// limit. The other three in-flight requests are cancelled.
						cancel()
					}
					continue
				}
				items[index].Readme = text
			}
		}()
	}
loop:
	for index, repo := range items {
		if _, err := parseRepo(repo.FullName); err != nil || repo.Private || excludedGameCandidate(repo) || metadataGameCandidate(repo, known) {
			continue
		}
		select {
		case work <- index:
		case <-ctx.Done():
			break loop
		}
	}
	close(work)
	wg.Wait()
	if firstError != nil {
		return firstError
	}
	return ctx.Err()
}
