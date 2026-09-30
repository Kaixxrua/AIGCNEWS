package projectsearch

import (
	"errors"
	"strings"
)

// FavoriteRepoLister 列出用户最近收藏的 GitHub repo_id（生产 =
// postgres.ProjectCollectionsRepository）。
type FavoriteRepoLister interface {
	ListFavoriteRepoIDs(userID, limit int) ([]string, error)
}

// FilteredVectorRepository 只在给定 repo_id 集合内做向量检索
// （MilvusVectorRepository.SearchRepoIDsWithin）。
type FilteredVectorRepository interface {
	SearchRepoIDsWithin(queryVector []float64, repoIDs []string, chunkLimit, repoLimit int, minScore float64) ([]SemanticHit, error)
}

// FavoritesSemanticConfig 对应 PROJECT_FAVORITES_SEMANTIC_* 配置；ChunkLimit
// 复用 PROJECT_SEMANTIC_CHUNK_LIMIT。
type FavoritesSemanticConfig struct {
	MinScore       float64
	TimeoutSeconds float64 // 列收藏 + embedding + 向量检索的总预算
	ChunkLimit     int     // 默认 800
	MaxFavorites   int     // 参与语义检索的最近收藏上限，默认 1000
}

// FavoritesSemantic 是 search_my_project_favorites 的语义通道：复用项目语义
// 向量集合，把检索限定在该用户自己的收藏里，返回相似度不低于 MinScore 的
// repo_id（按相似度降序）。
type FavoritesSemantic struct {
	favorites FavoriteRepoLister
	embedder  EmbeddingClient
	vectors   FilteredVectorRepository
	cfg       FavoritesSemanticConfig
}

func NewFavoritesSemantic(favorites FavoriteRepoLister, embedder EmbeddingClient, vectors FilteredVectorRepository, cfg FavoritesSemanticConfig) *FavoritesSemantic {
	if cfg.TimeoutSeconds <= 0 {
		cfg.TimeoutSeconds = 3
	}
	if cfg.ChunkLimit <= 0 {
		cfg.ChunkLimit = 800
	}
	if cfg.MaxFavorites <= 0 {
		cfg.MaxFavorites = 1000
	}
	return &FavoritesSemantic{favorites: favorites, embedder: embedder, vectors: vectors, cfg: cfg}
}

// SearchFavoriteRepoIDs 实现 mcpapp.FavoritesSemanticSearcher。空查询、匿名
// 或没有收藏时返回空结果且不触碰 embedding。
func (s *FavoritesSemantic) SearchFavoriteRepoIDs(userID int, query string) ([]string, error) {
	query = strings.TrimSpace(query)
	if query == "" || userID <= 0 {
		return nil, nil
	}
	if s.favorites == nil || s.embedder == nil || s.vectors == nil {
		return nil, errors.New("favorites semantic search: dependencies are not configured")
	}
	hits, err := runWithTimeout(maxSeconds(s.cfg.TimeoutSeconds), func() ([]SemanticHit, error) {
		repoIDs, err := s.favorites.ListFavoriteRepoIDs(userID, s.cfg.MaxFavorites)
		if err != nil || len(repoIDs) == 0 {
			return nil, err
		}
		vector, err := s.embedder.EmbedQuery(query)
		if err != nil {
			return nil, err
		}
		return s.vectors.SearchRepoIDsWithin(vector, repoIDs, s.cfg.ChunkLimit, len(repoIDs), s.cfg.MinScore)
	})
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(hits))
	for _, hit := range hits {
		ids = append(ids, hit.RepoID)
	}
	return ids, nil
}
