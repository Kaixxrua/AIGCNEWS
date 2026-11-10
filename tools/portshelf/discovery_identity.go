package main

import (
	"path"
	"regexp"
	"strings"
	"unicode"
)

// Game types are identity nouns here. Ordinary verbs such as "fighting" or
// "racing" elsewhere in a README are not evidence that its project is a game.
var gameTypeIdentity = regexp.MustCompile(`(?i)\b(?:roguelikes?|roguelites?|dungeon[ -]crawlers?|platformers?|shooters?|mmorpgs?|metroidvanias?|visual[ -]novels?|(?:arcade|tactical|[23]d|pseudo[ -]3d|first[ -]person|third[ -]person)[ -]shooters?|tower[ -]defen[cs]e(?:[ -]rts)?|(?:solitaire|patience)(?:/patience)? games?|city[ -]builders?|quiz (?:platform|game)|wordle|chess server|(?:physics|falling sand) sandbox|(?:mmo[ -])?rpg|rts|(?:an?|the) fps|4x[ -](?:strategy|game)|(?:fighting|racing|adventure|exploration|puzzle|rhythm|trading|combat|strategy)[ -]games?|(?:real[ -]time|turn[ -]based)[ -](?:strategy|tactics)(?:[ -]simulation)?)\b|(?:命令行|在线|联机|单机)?(?:斗地主|德州扑克|麻将|五子棋|国际象棋|扫雷|俄罗斯方块)`)
var unrelatedPurpose = regexp.MustCompile(`(?i)\b(?:storage engine|database (?:system|server|engine)|sql (?:parser|compiler|database)|(?:input|gesture|touch) (?:manager|component)|asset that|catalogue|catalog|directory|reference book|creation suite|fantasy console|desktop environment)\b`)
var developmentPurpose = regexp.MustCompile(`(?i)^(?:learn to|(?:create|build|make|generate|design) (?:your |a |an )?(?:games?|dialogs?|visual novels?|rpgs?))\b|\b(?:tutorial|course) (?:series|on|about|for (?:making|building|creating))\b`)
var indirectGameUse = regexp.MustCompile(`(?i)\bfor (?:games?|visual novels?|rpgs?|game engines?)(?:\s*[,/].*)?|\b(?:high|higher|stable|[0-9]+) fps\b`)
var dependencyEngine = regexp.MustCompile(`(?i)\b(?:for|using|with|in) (?:the |an? )?$`)
var readmeNotice = regexp.MustCompile(`(?i)^[^A-Za-z]*(?:note:|notice:|warning:|disclaimer:|this project is (?:no longer|not)|the project has not)`)
var noticeHeading = regexp.MustCompile(`(?i)^(?:notice|warning|disclaimer)(?:\b|$)`)
var identityHeading = regexp.MustCompile(`(?i)^(?:about|overview|introduction|what is|readme|project goals|supported games|简介|介绍)(?:\b|$)`)
var headingDecoration = regexp.MustCompile(`^[^A-Za-z\p{Han}]*`)
var pluralImplementations = regexp.MustCompile(`(?i)\b(?:clones|remakes|reimplementations|source[ -]?ports)\s+(?:of|for)\b`)
var collectionReadmePurpose = regexp.MustCompile(`(?i)\b(?:games? (?:database|catalogue|catalog|directory)|(?:list|catalogue|catalog|directory) of [^.\n]{0,90}games?(?: engines?)?|add new games or improve information|games (?:and their references|are stored in))\b`)
var nonIdentitySection = regexp.MustCompile(`(?i)^(?:sponsor(?:ed|s|ship)?(?: by)?|examples?|samples?|(?:engine )?showcase|games (?:made|built|using)|made with|powered by|used by|related projects?|references|credits|tutorials?|benchmarks?)(?:\b|$)|^(?:赞助|示例|样例|展示|相关项目|参考资料)`)
var readmeImage = regexp.MustCompile(`!\[[^\]\n]*\]\([^\)\n]*\)`)
var readmeLink = regexp.MustCompile(`\[([^\]\n]+)\]\([^\)\n]*\)`)
var htmlHeading = regexp.MustCompile(`(?is)<h([1-6])(?:\s[^>]*)?>(.*?)</h[1-6]>`)
var externalGameStatement = regexp.MustCompile(`(?i)(?:^|[.!?]\s+)[^.!?\n]*(?:used to (?:ship|create|build|make)|(?:example|sample) games?|games (?:made|built|created) with)[^.!?\n]*[.!?]?`)
var namedEngine = regexp.MustCompile(`\b([A-Z][A-Za-z0-9+#'.-]{1,50}(?:\s+[0-9IVX]+)?)\s+(?i:game\s+)?(?i:engine)\b`)
var paragraphList = regexp.MustCompile(`(?m)^\s*[-*]\s`)
var originalGameData = regexp.MustCompile(`(?i)\b(?:(?:original|retail|commercial) game (?:files|data|assets)|(?:need|require)[^.\n]{0,20}original data files|need to own [^.\n]{1,50}in order to play|reproduce the original game|copy [^.!\n]{0,50}world save|engine and mod code but not any game data|(?:requires?|needs?) [^.\n]{0,60}(?:copy of (?:the )?(?:original )?game|game data))`)

// Remove documents about other games before evaluating this project's role.
// Excluded sections are bounded by their actual Markdown heading level; a
// following About/Installation section is still available as evidence.
func discoveryReadmeText(raw string) string {
	text := readmeCode.ReplaceAllString(raw, " ")
	text = htmlHeading.ReplaceAllStringFunc(text, func(value string) string {
		m := htmlHeading.FindStringSubmatch(value)
		return "\n" + strings.Repeat("#", int(m[1][0]-'0')) + " " + m[2] + "\n"
	})
	text = readmeImage.ReplaceAllString(text, " ")
	text = readmeLink.ReplaceAllString(text, "$1")
	text = readmeMarkup.ReplaceAllString(text, " ")
	text = strings.NewReplacer("**", "", "__", "", "™", "", "®", "").Replace(text)
	var kept []string
	skipLevel := 0
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		level := len(trimmed) - len(strings.TrimLeft(trimmed, "#"))
		if level > 0 && level <= 6 && len(trimmed) > level && trimmed[level] == ' ' {
			title := headingDecoration.ReplaceAllString(strings.TrimSpace(trimmed[level:]), "")
			if skipLevel > 0 && level <= skipLevel {
				skipLevel = 0
			}
			if skipLevel == 0 && nonIdentitySection.MatchString(title) {
				skipLevel = level
			}
		}
		if skipLevel == 0 {
			kept = append(kept, line)
		}
	}
	text = strings.Join(kept, "\n")
	text = externalGameStatement.ReplaceAllString(text, " ")
	if len(text) > 12000 {
		text = text[:12000]
	}
	return text
}

func primaryGameType(text string) bool {
	if genericEngineMarker.MatchString(text) || developmentPurpose.MatchString(strings.TrimSpace(text)) {
		return false
	}
	return gameTypeIdentity.MatchString(indirectGameUse.ReplaceAllString(text, ""))
}

// Identify the project's introduction before setup/dependency details. Named
// About/Overview sections remain part of its identity; examples were removed
// earlier and cannot override the described purpose.
func discoveryReadmeIntro(text string) string {
	var lines []string
	bodySeen, skip, notice := false, false, false
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		level := len(trimmed) - len(strings.TrimLeft(trimmed, "#"))
		if level > 0 && level <= 6 && len(trimmed) > level && trimmed[level] == ' ' {
			title := headingDecoration.ReplaceAllString(strings.TrimSpace(trimmed[level:]), "")
			notice = noticeHeading.MatchString(title)
			if identityHeading.MatchString(title) {
				skip = false
			} else if bodySeen {
				skip = true
			}
		} else if !notice && len(trimmed) > 80 && !strings.HasPrefix(trimmed, "[") && !strings.HasPrefix(trimmed, "|") && !readmeNotice.MatchString(trimmed) {
			bodySeen = true
		}
		if !skip {
			lines = append(lines, line)
		}
	}
	intro := strings.Join(lines, "\n")
	if len(intro) > 2600 {
		intro = intro[:2600]
	}
	return intro
}

func standaloneGameParagraph(text string) bool {
	for _, paragraph := range strings.Split(text, "\n\n") {
		if paragraphList.MatchString(paragraph) {
			continue
		}
		paragraph = strings.Join(strings.Fields(paragraph), " ")
		if engineWord.MatchString(paragraph) || strings.HasPrefix(paragraph, "*") || strings.HasPrefix(paragraph, "-") || toolPurpose(paragraph) {
			continue
		}
		if primaryGameNoun.MatchString(paragraph) || (strings.Contains(strings.ToLower(paragraph), " is ") || strings.HasPrefix(strings.ToLower(paragraph), "a ") || strings.HasPrefix(strings.ToLower(paragraph), "an ")) && primaryGameType(paragraph) {
			return true
		}
	}
	return false
}

// Classify the described software's role, after removing dependency clauses.
// The noun after "for" names the tool's target, not the tool itself.
var softwareUtilityRole = regexp.MustCompile(`(?i)\b(?:translator|translation tool|game (?:translation|configuration|manager|management|save|scanner|overlay)|inventory system|virtual tabletop|DSL|RL game environments|reinforcement learning|(?:cards?|games?) (?:[^.\n]{0,12} )?(?:database|collections?)|docker image|modding API|(?:make and play|create and play) [a-z0-9 ]*mods|models, pre-configured|tools? (?:for|that)|core compiler|free and open source [^\n]{0,20}framework|development environment|game development software|tool for writing|graphics middleware|(?:head[ -]?tracking|lighting effects)|distributed [a-z]+ game server|(?:audio|rendering) engine|game distribution platform|mmorpg platform|(?:research|training|evaluation) platform|platform for (?:game )?research|base structure for|(?:python |AI )?bot that|mod editor|(?:translation|learning) [^.\n]{0,40}app for|petition to|curated list of mods|quadtree implementation|pixel-perfect [^\n]{0,30}paint remake|AI bots?|(?:NPC|AI) ?/ ?bot|AI bot|(?:jailbreak|custom) firmware|themed OS|cloud gaming|(?:idling|boosting) [^.\n]{0,35}game hours|installer for|lootfilter|modding tools?|counter mod|custom counter|mod[ -]manager|game (?:updater|patcher)|network(?:ing)? library)\b|(?:游戏|游戏存档|联机|配置)(?:管理器|工具|一键部署|部署面板)|(?:手游|游戏).*?(?:服务端框架|分布式服务器)|源码(?:集合|合集)|游戏合集|游戏框架|游戏配置解决方案|自动化框架|自动化(?:助手|工具|脚本)|阅读此书|(?:聊天.*(?:下棋|斗地主))`)
var aiUtilityPurpose = regexp.MustCompile(`(?i)^(?:(?:an?|the) )?(?:[a-z0-9-]+ )?AI for\b|\b(?:your|an?|the) AI agent (?:decompiles|compiles|generates)\b`)
var bareUtilitySubject = regexp.MustCompile(`(?i)^(?:[a-z0-9.+_/-]+[ \t]+){0,8}(?:tool|toolset|library|framework|plugin|component|renderer|translator|interpreter|visualizer|solution|service|launcher|workflow)\b`)
var constructionEnginePurpose = regexp.MustCompile(`(?i)\b(?:create [^.\n]{0,80}games|(?:make|build|making|building) (?:your|any|whatever|all type of|awesome|a) [^.\n]{0,50}(?:games?|MUD)|(?:visual |scene )?editor|creation suite)\b`)
var utilitySubject = regexp.MustCompile(`(?im)^[ \t]*(?:(?:[a-z0-9._-]+[ \t]+){1,5}is[ \t]+)?an?[ \t]+(?:[a-z0-9_-]+[ \t]+){0,8}(?:tool|toolset|library|framework|plugin|component|renderer|translator|interpreter|visualizer|solution|service|launcher|workflow)\b|^(?:practice your|use ai to|scans? |reduce the space|appear offline|application-based actions)\b`)
var selfGameClaim = regexp.MustCompile(`(?i)\b(?:an?|computer|browser|in-browser|video|online|[a-z-]+ building|singing|geography|source|exciting|royale|evolution|hell|[a-z]+ite) game\b|\bgame (?:developed|created|that|port)\b|\b(?:combat|city|space|flight) simulator\b|游戏(?:[，。！、/]|$)|(?:数独|魔方)游戏|\b(?:player[^.\n]{0,50}challenge|rules, more ways to play)\b|(?:原版所有功能|游戏体验|玩家[^。\n]{0,40}挑战)`)
var engineWord = regexp.MustCompile(`(?i)\bengine\b`)
var existingGameMods = regexp.MustCompile(`(?i)\bloading new games \(mods\)`)
var playableEngine = regexp.MustCompile(`(?is)\bengine.{0,160}(?:for playing|to play)\s+[*_]*[a-z0-9]`)
var gameRuntimePurpose = regexp.MustCompile(`(?i)\b(?:engine[\s\S]{0,160}(?:for playing|to play) [*_]*[A-Z]|game engine behind [^\n]{0,180}games|continuation of [^\n]{0,100}\bgames?\b|(?:game engine|engine) (?:used in|developed [^\n]{0,60} for) [^\n]{0,120}\b(?:games?|classic)\b|game data (?:from|remains)|server replacement for|plays [A-Z])`)
var originalExtension = regexp.MustCompile(`(?i)\bextension of [^.!\n]{0,70}original [^.!\n]{0,50}project\b`)
var roleNoun = regexp.MustCompile(`(?i)\b(?:tool|toolset|library|framework|plugin|component|renderer|translator|interpreter|visualizer|solution|service|launcher|workflow)\b`)
var rebuiltPlayableOriginals = regexp.MustCompile(`(?i)\b(?:rebuild|recreate|reimplement)[^.!\n]{0,120}\b(?:classic|original)\b[^.!\n]{0,120}\b(?:games?|rpgs?)[^.!\n]{0,70}\bplayable\b`)
var nativeRuntimeEvidence = regexp.MustCompile(`(?i)\b(?:native (?:[a-z0-9_-]+ )?(?:program|executable)|recompiled to run natively)\b`)
var engineShooter = regexp.MustCompile(`(?i)\bengine/(?:first person )?shooter\b`)
var targetClient = regexp.MustCompile(`(?i)\b([a-z0-9-]+) client\b`)
var playClientEvidence = regexp.MustCompile(`(?i)\b(?:single[ -]?player|gameplay|game physics|world interactions)\b`)
var gameAndEngine = regexp.MustCompile(`(?i)\bgame and\b`)
var likeTheGame = regexp.MustCompile(`(?i)\bis like the game\b`)
var namedGameVersion = regexp.MustCompile(`(?i)\b(?:version|implementation|source code|decompiled code|code) (?:of|for) the game\b`)
var explicitGameRuntime = regexp.MustCompile(`(?i)\b(?:compatible client of|terminal interface for|ports? the classic|game/engine|complete implementation of)\b`)
var purposeRecreation = regexp.MustCompile(`(?i)\b(?:re-?implement(?:ation|ed)?|remake|demake|recreation|clone|port|rewrite|decompilation|recompilation)(?:\s+[^.\n]{0,40})?\s+(?:of|for)\s+[^.\n]+`)
var primaryGameNoun = regexp.MustCompile(`(?i)\b(?:(?:computer|video)[ -]+|fan[ -]?)game\b|\bgame (?:inspired by|on steam|called|with)\b|\b(?:classic|tactical|block|gen [0-9]+) game\b`)
var gamePlayControls = regexp.MustCompile(`(?i)\b(?:game rules|continue game|restart level|remaining time)\b`)
var directRecompiledRuntime = regexp.MustCompile(`(?i)\brecompiled to run natively on\b`)
var reversedGame = regexp.MustCompile(`(?i)\b(?:(?:entire|original|whole) game (?:reversed|reimplemented|recreated)|game will behave the same)\b`)
var ownPlayHeading = regexp.MustCompile(`(?im)^#*[ \t]*play[ \t]+([^\n]{1,100})$`)
var supportedGameReleases = regexp.MustCompile(`(?is)supported games[^\n]*\n.{0,700}source code branch.{0,200}release`)
var gameSubjectPort = regexp.MustCompile(`(?i)\b(?:re-?implementation|recreation|remake|demake|game port|fan port)\b|\bclone[\x60* ]+of\b|\brewritten[ \t]+in\b`)

// A porting toolchain's name or a git clone command is not a game port.
// A stated porting target must match a specific topic supplied by the project.
func namedGamePorting(repo searchRepository, intro string) bool {
	for _, topic := range repo.Topics {
		if topic == "game" || topic == "games" || topic == "game-engine" || strings.HasPrefix(topic, "game-") || strings.Contains(topic, "tool") {
			continue
		}
		words := strings.FieldsFunc(topic, func(r rune) bool { return r == '-' || r == '_' || r == ' ' })
		for i, word := range words {
			words[i] = regexp.QuoteMeta(word)
		}
		if len(words) > 0 && regexp.MustCompile(`(?i)\bporting[ \t]+`+strings.Join(words, `[ _-]+`)+`\b`).MatchString(intro) {
			return true
		}
	}
	return false
}

func gameDomain(repo searchRepository) bool {
	for _, topic := range repo.Topics {
		lower := strings.ToLower(topic)
		if lower == "game" || lower == "games" || lower == "game-engine" || strings.HasSuffix(lower, "-game") || gameGenreMarker.MatchString(lower) {
			return true
		}
	}
	return false
}
func normalizedPurpose(text string) string {
	return strings.TrimLeftFunc(mentionedToolClause.ReplaceAllString(negatedToolClause.ReplaceAllString(text, ""), ""), func(r rune) bool { return !unicode.IsLetter(r) && !unicode.IsDigit(r) })
}
func toolPurpose(text string) bool {
	text = normalizedPurpose(text)
	role := softwareUtilityRole.FindStringIndex(text)
	subject := utilitySubject.FindStringIndex(text)
	if bare := bareUtilitySubject.FindStringIndex(text); bare != nil {
		subject = bare
	}
	if subject != nil {
		// The noun is the role; introductory adjectives and a game port's earlier
		// identity must not be mistaken for the role itself.
		nouns := roleNoun.FindAllStringIndex(text[:subject[1]], -1)
		if len(nouns) > 0 {
			subject = nouns[len(nouns)-1]
		}
		if role == nil || subject[0] < role[0] {
			role = subject
		}
	}
	if developmentPurpose.MatchString(text) || aiUtilityPurpose.MatchString(text) {
		return true
	}
	if role == nil {
		return false
	}
	for _, positive := range []*regexp.Regexp{portMarker, specificRecompilationMarker} {
		if claim := positive.FindStringIndex(text); claim != nil && claim[1] <= role[0] {
			return false
		}
	}
	return true
}

// The phrase "game engine" alone says nothing about a downloadable game.
// Keep dedicated compatibility engines when their target differs from the
// project's own engine brand and the README supplies runtime/play evidence.
func dedicatedEnginePurpose(repo searchRepository, intro, document string) bool {
	source := repo.Description + "\n" + intro
	if rebuiltPlayableOriginals.MatchString(intro) || engineShooter.MatchString(intro) || standaloneGameParagraph(intro) || originalGameData.MatchString(document) || portMarker.MatchString(intro) || gameRuntimePurpose.MatchString(source) || (primaryGameType(genericEngineMarker.ReplaceAllString(source, "")) && gameAndEngine.MatchString(source)) {
		return true
	}
	constructs := constructionEnginePurpose.MatchString(intro) || genericDevelopmentMarker.MatchString(intro)
	for _, index := range namedEngine.FindAllStringSubmatchIndex(source, -1) {
		if dependencyEngine.MatchString(source[max(0, index[0]-40):index[0]]) {
			continue
		}
		target := strings.ToLower(source[index[2]:index[3]])
		ownName := strings.TrimRight(strings.TrimSuffix(strings.ToLower(repo.Name), "engine"), "-_")
		ownRepo := strings.TrimRight(strings.TrimSuffix(strings.ToLower(path.Base(repo.FullName)), "engine"), "-_")
		if target == ownName || target == ownRepo {
			continue
		}
		switch target {
		case "game", "the", "this", "new", "modern", "cross-platform", "python", "java", "go", "swift", "javascript", "typescript", "rust", "kotlin", "as3", "c++", "c#", "lua", "html5", "web", "rts", "3d", "2d", "strategy", "interactive", "graphics", "front-end", "performance", "real-time", "modular", "rendering", "vulkan", "dx12", "c", "another":
			continue
		}
		if strings.Contains(strings.ToLower(document), target+" is the game") || !constructs && (namedTargetTopic(repo, target) || existingGameMods.MatchString(intro)) {
			return true
		}
	}
	return false
}

// A runtime client needs both a named target repeated by the project's topics
// and actual single-player/gameplay support. A general network client cannot
// qualify through the game topic alone.
func targetClientPurpose(repo searchRepository, intro, document string) bool {
	if !playClientEvidence.MatchString(document) {
		return false
	}
	for _, m := range targetClient.FindAllStringSubmatch(intro, -1) {
		for _, topic := range repo.Topics {
			if strings.EqualFold(m[1], topic) && topic != "game" && topic != "network" {
				return true
			}
		}
	}
	return false
}
func reconstructsGameEngine(repo searchRepository) bool {
	if genericEngineMarker.MatchString(repo.Description) || !strings.Contains(strings.ToLower(repo.Description), "engine implementation") {
		return false
	}
	for _, topic := range repo.Topics {
		if strings.EqualFold(topic, "engine-reconstruction") && gameDomain(repo) {
			return true
		}
	}
	return false
}

func compactIdentity(text string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			return unicode.ToLower(r)
		}
		return -1
	}, text)
}
func namedTargetTopic(repo searchRepository, target string) bool {
	target = compactIdentity(target)
	for _, topic := range repo.Topics {
		if compactIdentity(topic) == target {
			return true
		}
	}
	return false
}
func playOwnProject(repo searchRepository, intro string) bool {
	if !gameDomain(repo) {
		return false
	}
	for _, match := range ownPlayHeading.FindAllStringSubmatch(intro, -1) {
		name := compactIdentity(match[1])
		if name == compactIdentity(repo.Name) || name == compactIdentity(path.Base(repo.FullName)) {
			return true
		}
	}
	return false
}
