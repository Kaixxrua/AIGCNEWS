package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

type Game struct {
	Repo        string `json:"repo"`
	Name        string `json:"name"`
	Subtitle    string `json:"subtitle"`
	Category    string `json:"category"`
	Description string `json:"description"`
	DataNote    string `json:"dataNote"`
	Guide       string `json:"guide"`
	Mark        string `json:"mark"`
	Color       string `json:"color"`
	Stars       *int   `json:"stars,omitempty"`
}

type Snapshot struct {
	Stars            int      `json:"stars"`
	PushedAt         string   `json:"pushedAt"`
	StarsCheckedAt   string   `json:"starsCheckedAt"`
	ReleaseCheckedAt string   `json:"releaseCheckedAt"`
	Release          *Release `json:"release,omitempty"`
	Error            string   `json:"error,omitempty"`
}

type diskState struct {
	Games     []Game              `json:"games"`
	Snapshots map[string]Snapshot `json:"snapshots"`
}

type Library struct {
	mu    sync.RWMutex
	root  string
	state diskState
}

const maxLibraryBytes = 16 << 20

func newLibrary(root string) (*Library, error) {
	root, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	if err = os.MkdirAll(root, 0700); err != nil {
		return nil, err
	}
	seed, err := assets.ReadFile("snapshot.json")
	if err != nil {
		return nil, err
	}
	l := &Library{root: root, state: diskState{Games: []Game{}, Snapshots: map[string]Snapshot{}}}
	if err = json.Unmarshal(seed, &l.state.Snapshots); err != nil {
		return nil, fmt.Errorf("内置游戏信息无效：%w", err)
	}
	f, err := os.Open(filepath.Join(root, "library.json"))
	if err == nil {
		defer f.Close()
		b, readErr := io.ReadAll(io.LimitReader(f, maxLibraryBytes+1))
		if readErr != nil {
			return nil, readErr
		}
		var saved diskState
		if len(b) > maxLibraryBytes || json.Unmarshal(b, &saved) != nil || len(saved.Games) > 500 {
			return nil, errors.New("游戏库记录损坏，请先备份 library.json 后再恢复")
		}
		l.state.Games = saved.Games
		if l.state.Snapshots == nil {
			l.state.Snapshots = map[string]Snapshot{}
		}
		for repo, snapshot := range saved.Snapshots {
			l.state.Snapshots[strings.ToLower(repo)] = snapshot
		}
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	if l.state.Games == nil {
		l.state.Games = []Game{}
	}
	if l.state.Snapshots == nil {
		l.state.Snapshots = map[string]Snapshot{}
	}
	for i := range l.state.Games {
		if err := validateGame(&l.state.Games[i]); err != nil {
			return nil, fmt.Errorf("游戏库项目无效：%w", err)
		}
	}
	clean := make(map[string]Snapshot, len(l.state.Snapshots))
	for repo, snapshot := range l.state.Snapshots {
		valid, err := parseRepo(repo)
		if err != nil {
			return nil, errors.New("游戏库包含无效的项目地址")
		}
		if snapshot.Release != nil {
			release, err := prepareRelease(valid, *snapshot.Release, "")
			if err != nil {
				return nil, fmt.Errorf("游戏库 %s 的发布信息无效：%w", valid, err)
			}
			snapshot.Release = &release
		}
		clean[strings.ToLower(valid)] = snapshot
	}
	l.state.Snapshots = clean
	return l, nil
}

func validateGame(g *Game) error {
	repo, err := parseRepo(g.Repo)
	if err != nil {
		return err
	}
	g.Repo = repo
	g.Guide = "https://github.com/" + repo + "#readme"
	if g.Name == "" {
		g.Name = strings.Split(repo, "/")[1]
	}
	return nil
}

func randomID() string {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}

// The caller holds l.mu. Publish new memory only after its disk replacement succeeds.
func (l *Library) save(next diskState) error {
	b, err := json.MarshalIndent(next, "", "  ")
	if err != nil {
		return err
	}
	if len(b) > maxLibraryBytes {
		return errors.New("游戏库缓存过大，无法保存")
	}
	f, err := os.CreateTemp(l.root, ".library-*")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(b); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = replaceFile(name, filepath.Join(l.root, "library.json")); err != nil {
		return err
	}
	l.state = next
	return nil
}

func cloneSnapshot(snapshot Snapshot) Snapshot {
	if snapshot.Release != nil {
		release := *snapshot.Release
		release.Assets = append([]Asset{}, release.Assets...)
		snapshot.Release = &release
	}
	return snapshot
}

func cloneGame(game Game) Game {
	if game.Stars != nil {
		stars := *game.Stars
		game.Stars = &stars
	}
	return game
}

func cloneState(state diskState) diskState {
	next := diskState{Games: make([]Game, len(state.Games)), Snapshots: make(map[string]Snapshot, len(state.Snapshots))}
	for i, game := range state.Games {
		next.Games[i] = cloneGame(game)
	}
	for repo, snapshot := range state.Snapshots {
		next.Snapshots[repo] = cloneSnapshot(snapshot)
	}
	return next
}

func (l *Library) snapshot() diskState {
	l.mu.RLock()
	defer l.mu.RUnlock()
	return cloneState(l.state)
}

func (l *Library) add(game Game, snapshot Snapshot) error {
	if err := validateGame(&game); err != nil {
		return err
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	for _, existing := range l.state.Games {
		if strings.EqualFold(existing.Repo, game.Repo) {
			return nil
		}
	}
	if len(l.state.Games) >= 500 {
		return errors.New("游戏库最多添加 500 个自定义项目")
	}
	next := cloneState(l.state)
	next.Games = append(next.Games, cloneGame(game))
	next.Snapshots[strings.ToLower(game.Repo)] = cloneSnapshot(snapshot)
	return l.save(next)
}

func (l *Library) updateSnapshot(repo string, snapshot Snapshot) error {
	l.mu.Lock()
	defer l.mu.Unlock()
	next := cloneState(l.state)
	next.Snapshots[strings.ToLower(repo)] = cloneSnapshot(snapshot)
	return l.save(next)
}
