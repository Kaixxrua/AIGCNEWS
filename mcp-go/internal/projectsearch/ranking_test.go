package projectsearch

import (
	"fmt"
	"reflect"
	"slices"
	"testing"
)

// 展示序用例与 backend/tests/test_project_search_ranking.py 逐字镜像，
// 两侧同一输入必须给出同一顺序。

func TestPopularityKeyWeighsRecentGrowthAndTotalStars(t *testing.T) {
	if got := PopularityKey(Popularity{WeeklyGrowth: 99, Stars: 9_999}); got != 100*10_000 {
		t.Fatalf("PopularityKey = %d", got)
	}
	if got := PopularityKey(Popularity{WeeklyGrowth: -5, Stars: -1}); got != 1 {
		t.Fatalf("negative inputs = %d, want 1", got)
	}
	if PopularityKey(Popularity{WeeklyGrowth: 5_000, Stars: 3_000}) <= PopularityKey(Popularity{Stars: 200_000}) {
		t.Fatal("a fast-rising newcomer must outrank a stagnant giant")
	}
}

func TestPopularityOrderingLiftsRelevantPopularCandidate(t *testing.T) {
	got := OrderCandidatesByPopularity(
		[]string{"owner/a", "owner/b", "owner/c"},
		map[string]Popularity{
			"owner/a": {Stars: 1_000},
			"owner/b": {Stars: 1_000},
			"owner/c": {WeeklyGrowth: 500, Stars: 50_000},
		},
		"", nil,
	)
	want := []string{"owner/a", "owner/c", "owner/b"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("order = %v, want %v", got, want)
	}
}

func TestPopularityOrderingKeepsWeaklyRelevantHitOffPageOne(t *testing.T) {
	ids := make([]string, 40)
	for i := range ids {
		ids[i] = fmt.Sprintf("owner/c%02d", i)
	}
	got := OrderCandidatesByPopularity(ids, map[string]Popularity{"owner/c39": {WeeklyGrowth: 20_000, Stars: 200_000}}, "", nil)
	if index := slices.Index(got, "owner/c39"); index != 22 {
		t.Fatalf("owner/c39 index = %d, want 22", index)
	}
	if !reflect.DeepEqual(got[:22], ids[:22]) {
		t.Fatalf("prefix = %v", got[:22])
	}
}

func TestPopularityOrderingPinsExactMatchFirst(t *testing.T) {
	got := OrderCandidatesByPopularity(
		[]string{"owner/viral", "Owner/Exact-Tool"},
		map[string]Popularity{"owner/viral": {WeeklyGrowth: 20_000, Stars: 200_000}, "Owner/Exact-Tool": {Stars: 5}},
		"owner/exact-tool", nil,
	)
	want := []string{"Owner/Exact-Tool", "owner/viral"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("order = %v, want %v", got, want)
	}
}

func TestPopularityOrderingPinnedEntriesKeepFusionOrderAndExactStaysFirst(t *testing.T) {
	got := OrderCandidatesByPopularity(
		[]string{"owner/viral", "owner/second-fit", "Owner/Exact-Tool", "owner/first-fit"},
		map[string]Popularity{
			"owner/viral":      {WeeklyGrowth: 20_000, Stars: 200_000},
			"owner/first-fit":  {Stars: 500},
			"owner/second-fit": {Stars: 600},
			"Owner/Exact-Tool": {Stars: 5},
		},
		"owner/exact-tool", []string{"owner/first-fit", "owner/second-fit"},
	)
	want := []string{"Owner/Exact-Tool", "owner/second-fit", "owner/first-fit", "owner/viral"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("order = %v, want %v", got, want)
	}
}

func TestPopularityOrderingTreatsMissingPopularityAsZero(t *testing.T) {
	got := OrderCandidatesByPopularity(
		[]string{"owner/a", "owner/b", "owner/c"},
		map[string]Popularity{"owner/c": {WeeklyGrowth: 50, Stars: 30_000}},
		"", nil,
	)
	want := []string{"owner/a", "owner/c", "owner/b"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("order = %v, want %v", got, want)
	}
}
