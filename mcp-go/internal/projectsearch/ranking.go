package projectsearch

import (
	"math"
	"sort"
	"strings"

	"aigcnews/mcp-go/internal/projectsem"
)

// LexicalCandidate is the projectsearch-facing alias of the frozen semantic
// retrieval candidate shape.
type LexicalCandidate = projectsem.LexicalCandidate

// Popularity is the long-term heat of a candidate: star growth over the
// recent window (see GetProjectPopularityMap) and total stars.
type Popularity struct {
	WeeklyGrowth int
	Stars        int
}

// Relevance dominates the blended display order; mirrors RELEVANCE_WEIGHT and
// POPULARITY_WEIGHT in backend/app/services/project_search_ranking.py.
const (
	relevanceWeight  = 2.0
	popularityWeight = 1.0
)

const rankingK = 60

// RankLegacyProjectCandidateIDs reproduces the two-lane RRF used by the
// legacy search path. Each lane de-duplicates independently, preserving the
// source's literal (rather than case-folded) repository identity.
func RankLegacyProjectCandidateIDs(lexicalRepoIDs, semanticRepoIDs []string, rankConstant, limit int) []string {
	if rankConstant <= 0 {
		rankConstant = rankingK
	}
	if limit <= 0 {
		limit = 200
	}
	scores := map[string]float64{}
	best := map[string]int{}
	for _, lane := range []struct {
		weight float64
		ids    []string
	}{
		{0.45, lexicalRepoIDs},
		{0.55, semanticRepoIDs},
	} {
		seen := map[string]bool{}
		for rank, raw := range lane.ids {
			id := strings.TrimSpace(raw)
			if id == "" || seen[id] {
				continue
			}
			seen[id] = true
			r := rank + 1
			scores[id] += lane.weight / float64(rankConstant+r)
			if old, ok := best[id]; !ok || r < old {
				best[id] = r
			}
		}
	}
	ids := make([]string, 0, len(scores))
	for id := range scores {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool {
		if scores[ids[i]] != scores[ids[j]] {
			return scores[ids[i]] > scores[ids[j]]
		}
		if best[ids[i]] != best[ids[j]] {
			return best[ids[i]] < best[ids[j]]
		}
		return ids[i] < ids[j]
	})
	if len(ids) > limit {
		ids = ids[:limit]
	}
	return ids
}

// RankV2ProjectCandidateIDs fuses strict lexical, relaxed lexical and semantic
// lanes, then applies the optional adoption ballast to already eligible IDs.
func RankV2ProjectCandidateIDs(strict, relaxed []LexicalCandidate, semantic []string, exactRepoID string, rankConstant, limit int, adoptionStars map[string]int, adoptionWeight float64) []string {
	if rankConstant <= 0 {
		rankConstant = rankingK
	}
	if limit <= 0 {
		limit = 200
	}
	scores := map[string]float64{}
	best := map[string]int{}
	coverage := map[string]int{}
	strength := map[string]int{}
	profileCoverage := map[string]int{}
	artifactMismatch := map[string]bool{}
	add := func(weight float64, ids []string, candidates map[string]LexicalCandidate) {
		seen := map[string]bool{}
		for rank, raw := range ids {
			id := strings.TrimSpace(raw)
			if id == "" || seen[id] {
				continue
			}
			seen[id] = true
			r := rank + 1
			scores[id] += weight / float64(rankConstant+r)
			if old, ok := best[id]; !ok || r < old {
				best[id] = r
			}
			if candidate, ok := candidates[id]; ok {
				if candidate.TermCoverage > coverage[id] {
					coverage[id] = candidate.TermCoverage
				}
				if candidate.MatchStrength > strength[id] {
					strength[id] = candidate.MatchStrength
				}
				profileCoverage[id] = max(profileCoverage[id], candidate.ProfileScore)
				artifactMismatch[id] = candidate.ArtifactMismatch
			}
		}
	}
	strictMap := make(map[string]LexicalCandidate, len(strict))
	relaxedMap := make(map[string]LexicalCandidate, len(relaxed))
	strictIDs := make([]string, 0, len(strict))
	relaxedIDs := make([]string, 0, len(relaxed))
	for _, c := range strict {
		strictMap[strings.TrimSpace(c.RepoID)] = c
		strictIDs = append(strictIDs, c.RepoID)
	}
	for _, c := range relaxed {
		relaxedMap[strings.TrimSpace(c.RepoID)] = c
		relaxedIDs = append(relaxedIDs, c.RepoID)
	}
	add(0.45, strictIDs, strictMap)
	add(0.15, relaxedIDs, relaxedMap)
	add(0.40, semantic, nil)
	if adoptionWeight > 0 && len(adoptionStars) > 0 {
		maxStars := 0
		for rawID, stars := range adoptionStars {
			id := strings.TrimSpace(rawID)
			if _, ok := scores[id]; !ok || stars <= 0 {
				continue
			}
			if stars > maxStars {
				maxStars = stars
			}
		}
		if maxStars > 0 {
			denominator := math.Log1p(float64(maxStars))
			if denominator > 0 {
				for rawID, stars := range adoptionStars {
					id := strings.TrimSpace(rawID)
					if _, ok := scores[id]; ok && stars > 0 {
						scores[id] += adoptionWeight * math.Log1p(float64(stars)) / denominator
					}
				}
			}
		}
	}
	exact := strings.ToLower(strings.TrimSpace(exactRepoID))
	ids := make([]string, 0, len(scores))
	for id := range scores {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool {
		a, b := ids[i], ids[j]
		exactA := exact != "" && strings.EqualFold(a, exact)
		exactB := exact != "" && strings.EqualFold(b, exact)
		if exactA != exactB {
			return exactA
		}
		_, strictA := strictMap[a]
		_, strictB := strictMap[b]
		if strictA != strictB {
			return strictA
		}
		if artifactMismatch[a] != artifactMismatch[b] {
			return !artifactMismatch[a]
		}
		if profileCoverage[a] != profileCoverage[b] {
			return profileCoverage[a] > profileCoverage[b]
		}
		if scores[a] != scores[b] {
			return scores[a] > scores[b]
		}
		if strength[a] != strength[b] {
			return strength[a] > strength[b]
		}
		if coverage[a] != coverage[b] {
			return coverage[a] > coverage[b]
		}
		if best[a] != best[b] {
			return best[a] < best[b]
		}
		return a < b
	})
	if len(ids) > limit {
		ids = ids[:limit]
	}
	return ids
}

// PopularityKey is (1+weekly growth)·(1+stars), the integer equivalent of the
// sum of their log1p values, so both languages compare it exactly.
func PopularityKey(p Popularity) int64 {
	return (1 + int64(max(p.WeeklyGrowth, 0))) * (1 + int64(max(p.Stars, 0)))
}

// OrderCandidatesByPopularity mirrors order_candidates_by_popularity: exact
// match first, then strict-pinned ids in fusion order, then the rest by
// relevanceWeight/(k+fusion rank) + popularityWeight/(k+popularity rank),
// ties falling back to fusion order.
func OrderCandidatesByPopularity(repoIDs []string, popularity map[string]Popularity, exactRepoID string, pinnedRepoIDs []string) []string {
	fusion := make(map[string]int, len(repoIDs))
	for i, id := range repoIDs {
		fusion[id] = i
	}
	pinned := make(map[string]bool, len(pinnedRepoIDs))
	for _, id := range pinnedRepoIDs {
		pinned[id] = true
	}
	byPopularity := append([]string(nil), repoIDs...)
	sort.SliceStable(byPopularity, func(i, j int) bool {
		a, b := PopularityKey(popularity[byPopularity[i]]), PopularityKey(popularity[byPopularity[j]])
		if a != b {
			return a > b
		}
		return fusion[byPopularity[i]] < fusion[byPopularity[j]]
	})
	popularityRank := make(map[string]int, len(byPopularity))
	for i, id := range byPopularity {
		popularityRank[id] = i + 1
	}
	exact := strings.ToLower(strings.TrimSpace(exactRepoID))
	tierOf := func(id string) int {
		if exact != "" && strings.EqualFold(id, exact) {
			return 0
		}
		if pinned[id] {
			return 1
		}
		return 2
	}
	blended := func(id string) float64 {
		return relevanceWeight/float64(rankingK+fusion[id]+1) + popularityWeight/float64(rankingK+popularityRank[id])
	}
	out := append([]string(nil), repoIDs...)
	sort.SliceStable(out, func(i, j int) bool {
		a, b := out[i], out[j]
		tierA, tierB := tierOf(a), tierOf(b)
		if tierA != tierB {
			return tierA < tierB
		}
		if tierA == 2 {
			if sa, sb := blended(a), blended(b); sa != sb {
				return sa > sb
			}
		}
		return fusion[a] < fusion[b]
	})
	return out
}
