package main

import (
	"archive/zip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

const sourceBundleVersion = 1
const maxSourceBytes int64 = 2 << 30
const maxSourceExpandedBytes uint64 = 8 << 30
const maxBundleBytes int64 = maxTransferBytes + maxSourceBytes + 32<<20

var commitPattern = regexp.MustCompile(`^[0-9a-f]{40}$`)
var sha256Pattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

// Resolve the actual release tag, never a branch or a default-branch archive.
// Annotated tags may reference another annotated tag; pin the final commit.
func (g *GitHub) releaseCommit(ctx context.Context, repo, tag string) (string, error) {
	valid, err := parseRepo(repo)
	if err != nil || tag == "" || len(tag) > 255 || strings.ContainsAny(tag, "\x00\r\n") {
		return "", errors.New("发布版本标签无效，无法获取对应版本源码")
	}
	type gitObject struct {
		Type string `json:"type"`
		SHA  string `json:"sha"`
	}
	var ref struct {
		Ref    string    `json:"ref"`
		Object gitObject `json:"object"`
	}
	if err := g.get(ctx, "/repos/"+valid+"/git/ref/tags/"+url.PathEscape(tag), &ref); err != nil {
		return "", fmt.Errorf("无法核实发布版本源码：%w", err)
	}
	if ref.Ref != "refs/tags/"+tag {
		return "", errors.New("GitHub 返回的源码标签与发布版本不符")
	}
	object := ref.Object
	for depth := 0; depth < 8; depth++ {
		if !commitPattern.MatchString(object.SHA) {
			return "", errors.New("源码提交编号无效")
		}
		if object.Type == "commit" {
			return object.SHA, nil
		}
		if object.Type != "tag" {
			return "", errors.New("发布标签未指向源码提交")
		}
		var annotated struct {
			SHA    string    `json:"sha"`
			Object gitObject `json:"object"`
		}
		if err := g.get(ctx, "/repos/"+valid+"/git/tags/"+object.SHA, &annotated); err != nil {
			return "", fmt.Errorf("无法解析发布源码标签：%w", err)
		}
		if annotated.SHA != object.SHA {
			return "", errors.New("GitHub 返回的源码标签对象不符")
		}
		object = annotated.Object
	}
	return "", errors.New("发布源码标签嵌套过多，无法确认对应提交")
}

func sourceArchiveURL(repo, commit string) string {
	return "https://codeload.github.com/" + repo + "/zip/" + commit
}

func validSourceTarget(target *url.URL) bool {
	if target == nil || target.Scheme != "https" || target.Host != "codeload.github.com" || target.User != nil || target.Port() != "" || target.RawQuery != "" || target.ForceQuery || target.Fragment != "" {
		return false
	}
	parts := strings.Split(strings.TrimPrefix(target.Path, "/"), "/")
	return len(parts) == 4 && repoPattern.MatchString(parts[0]+"/"+parts[1]) && parts[2] == "zip" && commitPattern.MatchString(parts[3])
}

func sourceArchiveName(job TransferJob) string {
	return "portshelf-source-" + job.SourceCommit + ".zip"
}
func bundleName(job TransferJob) string {
	prefix := strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_' || r == '.' {
			return r
		}
		return '_'
	}, job.Repo+"-"+job.Version+"-"+job.Arch)
	if len(prefix) > 100 {
		prefix = prefix[:100]
	}
	return "PortShelf-" + prefix + "-with-source.zip"
}

func transferPayload(job TransferJob) (string, string) {
	if job.BundleVersion == sourceBundleVersion && job.BundleSHA256 != "" {
		return job.BundlePath, job.BundleSHA256
	}
	return job.DownloadPath, job.SHA256
}

func hasSourceBundle(job TransferJob) bool {
	return job.BundleVersion == sourceBundleVersion && commitPattern.MatchString(job.SourceCommit) &&
		sha256Pattern.MatchString(job.SourceSHA256) && sha256Pattern.MatchString(job.BundleSHA256) &&
		job.SourceSize > 0 && job.SourceSize <= maxSourceBytes && job.BundleSize > 0 && job.BundleSize <= maxBundleBytes &&
		job.SourcePath != "" && job.BundlePath != "" && job.SourceURL == sourceArchiveURL(job.Repo, job.SourceCommit)
}

// Open a managed file without following symlinks at any path component. The
// Root handles keep the file inside the downloaded task directory throughout.
func (m *transferManager) openManagedFile(target string) (*os.File, error) {
	if !m.ownedDownloadPath(target) {
		return nil, errors.New("文件不属于下载目录")
	}
	rootInfo, err := os.Lstat(m.downloadDir)
	if err != nil || !rootInfo.IsDir() || rootInfo.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("下载目录不安全")
	}
	root, err := os.OpenRoot(m.downloadDir)
	if err != nil {
		return nil, err
	}
	defer root.Close()
	opened, err := root.Stat(".")
	if err != nil || !os.SameFile(rootInfo, opened) {
		return nil, errors.New("下载目录已变化")
	}
	relative, _ := filepath.Rel(m.downloadDir, target)
	parent, name := filepath.Dir(relative), filepath.Base(relative)
	info, err := root.Lstat(parent)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("游戏目录不安全")
	}
	directory, err := root.OpenRoot(parent)
	if err != nil {
		return nil, err
	}
	defer directory.Close()
	opened, err = directory.Stat(".")
	if err != nil || !os.SameFile(info, opened) {
		return nil, errors.New("游戏目录已变化")
	}
	info, err = directory.Lstat(name)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("文件不安全")
	}
	file, err := directory.Open(name)
	if err != nil {
		return nil, err
	}
	opened, err = file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		file.Close()
		return nil, errors.New("文件已变化")
	}
	return file, nil
}

func hashFile(ctx context.Context, file *os.File, limit int64) (string, int64, error) {
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		return "", 0, err
	}
	hash := sha256.New()
	writer := &countingDownload{writer: hash, ctx: ctx, progress: func(int64, int64) {}}
	n, err := io.Copy(writer, io.LimitReader(file, limit+1))
	if err != nil || n <= 0 || n > limit {
		return "", n, errors.New("文件读取不完整或超过大小上限")
	}
	return hex.EncodeToString(hash.Sum(nil)), n, nil
}

func (m *transferManager) verifyManaged(ctx context.Context, target, digest string, size int64) bool {
	if !sha256Pattern.MatchString(digest) || size <= 0 || size > maxBundleBytes {
		return false
	}
	file, err := m.openManagedFile(target)
	if err != nil {
		return false
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || info.Size() != size {
		return false
	}
	actual, n, err := hashFile(ctx, file, size)
	return err == nil && n == size && actual == digest
}

func (m *transferManager) sourceDirectory(job TransferJob) (*os.Root, error) {
	rootInfo, err := os.Lstat(m.downloadDir)
	if err != nil || !rootInfo.IsDir() || rootInfo.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("下载目录不安全")
	}
	root, err := os.OpenRoot(m.downloadDir)
	if err != nil {
		return nil, err
	}
	defer root.Close()
	openedRoot, err := root.Stat(".")
	if err != nil || !os.SameFile(rootInfo, openedRoot) {
		return nil, errors.New("下载目录已变化")
	}
	if err := root.Mkdir(job.ID, 0700); err != nil && !errors.Is(err, os.ErrExist) {
		return nil, err
	}
	info, err := root.Lstat(job.ID)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("游戏目录不安全")
	}
	directory, err := root.OpenRoot(job.ID)
	if err != nil {
		return nil, err
	}
	opened, err := directory.Stat(".")
	if err != nil || !os.SameFile(info, opened) {
		directory.Close()
		return nil, errors.New("游戏目录已变化")
	}
	return directory, nil
}

// Validate every compressed member (including its CRC), without extracting or
// running any archive contents. Bound both entry count and expanded bytes.
func validateSourceZIP(ctx context.Context, file *os.File, size int64, repo, commit string) (map[string][]byte, error) {
	reader, err := zip.NewReader(file, size)
	if err != nil || len(reader.File) == 0 || len(reader.File) > 100_000 {
		return nil, errors.New("源码不是完整有效的 ZIP 归档")
	}
	repoName := strings.Split(repo, "/")[1]
	rootName := ""
	var total uint64
	licenses := map[string][]byte{}
	seen := map[string]bool{}
	for _, member := range reader.File {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		name := strings.TrimSuffix(member.Name, "/")
		entryRoot := strings.SplitN(name, "/", 2)[0]
		if rootName == "" {
			rootName = entryRoot
		}
		if name == "" || name != path.Clean(name) || strings.ContainsAny(name, "\\\x00") || entryRoot != rootName || !strings.HasSuffix(entryRoot, "-"+commit) || !strings.EqualFold(strings.TrimSuffix(entryRoot, "-"+commit), repoName) || seen[member.Name] {
			return nil, errors.New("源码归档的目录结构无效")
		}
		if name == rootName && !member.FileInfo().IsDir() {
			return nil, errors.New("源码归档根目录无效")
		}
		seen[member.Name] = true
		if member.UncompressedSize64 > maxSourceExpandedBytes-total {
			return nil, errors.New("源码展开大小超过 8 GiB 上限")
		}
		total += member.UncompressedSize64
		body, err := member.Open()
		if err != nil {
			return nil, errors.New("源码归档无法读取")
		}
		nameInRepo := strings.TrimPrefix(name, rootName+"/")
		upper := strings.ToUpper(nameInRepo)
		license := validDownloadName(nameInRepo) && member.Mode().IsRegular() && !strings.Contains(nameInRepo, "/") && (strings.HasPrefix(upper, "LICENSE") || strings.HasPrefix(upper, "LICENCE") || strings.HasPrefix(upper, "COPYING") || strings.HasPrefix(upper, "NOTICE")) && !member.FileInfo().IsDir() && member.UncompressedSize64 <= 4<<20 && len(licenses) < 20
		var sink io.Writer = io.Discard
		var buffer strings.Builder
		if license {
			sink = &buffer
		}
		n, copyErr := io.Copy(&countingDownload{writer: sink, ctx: ctx, progress: func(int64, int64) {}}, io.LimitReader(body, int64(member.UncompressedSize64)+1))
		closeErr := body.Close()
		if copyErr != nil || closeErr != nil || uint64(n) != member.UncompressedSize64 {
			return nil, errors.New("源码归档未通过完整性校验")
		}
		if license {
			licenses[nameInRepo] = []byte(buffer.String())
		}
	}
	return licenses, nil
}

func (m *transferManager) downloadSource(ctx context.Context, job TransferJob) (string, string, int64, error) {
	if !commitPattern.MatchString(job.SourceCommit) {
		return "", "", 0, errors.New("源码提交编号无效")
	}
	if m.verifyManaged(ctx, job.SourcePath, job.SourceSHA256, job.SourceSize) {
		return job.SourcePath, job.SourceSHA256, job.SourceSize, nil
	}
	directory, err := m.sourceDirectory(job)
	if err != nil {
		return "", "", 0, err
	}
	defer directory.Close()
	name := sourceArchiveName(job)
	target := filepath.Join(m.downloadDir, job.ID, name)
	// A previous process may have renamed a complete archive before saving its
	// receipt. Re-fetch and compare before adopting any existing final file.
	existing := false
	if info, err := directory.Lstat(name); err == nil {
		if !info.Mode().IsRegular() {
			return "", "", 0, errors.New("已有同名文件不安全，原文件会保留")
		}
		existing = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", "", 0, err
	}
	partial := name + ".part-" + randomID()
	file, err := directory.OpenFile(partial, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0600)
	if err != nil {
		return "", "", 0, errors.New("无法创建源码下载文件")
	}
	defer func() { file.Close(); directory.Remove(partial) }()
	downloadCtx, cancel := context.WithTimeout(ctx, 2*time.Hour)
	defer cancel()
	request, err := http.NewRequestWithContext(downloadCtx, http.MethodGet, sourceArchiveURL(job.Repo, job.SourceCommit), nil)
	if err != nil || !validSourceTarget(request.URL) {
		return "", "", 0, errors.New("源码下载地址无效")
	}
	request.Header.Set("User-Agent", "PortShelf/"+version)
	request.Header.Set("Accept-Encoding", "identity")
	response, err := m.client.Do(request)
	if err != nil {
		return "", "", 0, errors.New("连接 GitHub 源码服务器失败，请重试")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return "", "", 0, fmt.Errorf("GitHub 源码下载返回 HTTP %d，请重试", response.StatusCode)
	}
	if response.ContentLength > maxSourceBytes {
		return "", "", 0, errors.New("源码归档超过 2 GiB 上限")
	}
	hash := sha256.New()
	writer := &countingDownload{writer: io.MultiWriter(file, hash), ctx: downloadCtx, total: response.ContentLength, progress: m.progress(job.ID)}
	size, err := io.Copy(writer, io.LimitReader(response.Body, maxSourceBytes+1))
	if err != nil || size <= 0 || size > maxSourceBytes || response.ContentLength >= 0 && response.ContentLength != size {
		return "", "", 0, errors.New("源码下载未完整结束，请重试")
	}
	if _, err := validateSourceZIP(downloadCtx, file, size, job.Repo, job.SourceCommit); err != nil {
		return "", "", 0, err
	}
	digest := hex.EncodeToString(hash.Sum(nil))
	if err := file.Sync(); err != nil {
		return "", "", 0, errors.New("源码文件写入失败")
	}
	if err := file.Close(); err != nil {
		return "", "", 0, err
	}
	if existing {
		if !m.verifyManaged(ctx, target, digest, size) {
			return "", "", 0, errors.New("已有同名文件与源码归档不一致，原文件会保留")
		}
	} else if err := directory.Rename(partial, name); err != nil {
		return "", "", 0, errors.New("无法保存完整源码归档")
	}
	return target, digest, size, nil
}

type bundleManifest struct {
	Format           int      `json:"format"`
	Repo             string   `json:"repo"`
	ProjectName      string   `json:"projectName"`
	GameNameZh       string   `json:"gameNameZh,omitempty"`
	GameNameOriginal string   `json:"gameNameOriginal,omitempty"`
	Version          string   `json:"version"`
	Arch             string   `json:"arch"`
	SupportedSystems []string `json:"supportedSystems"`
	ReleaseURL       string   `json:"releaseUrl"`
	AssetName        string   `json:"assetName"`
	AssetSHA256      string   `json:"assetSha256"`
	SourceCommit     string   `json:"sourceCommit"`
	SourceURL        string   `json:"sourceUrl"`
	SourceSHA256     string   `json:"sourceSha256"`
	Description      string   `json:"descriptionZh"`
	Requirements     string   `json:"requirements"`
	Guide            string   `json:"guide"`
}

func (m *transferManager) createSourceBundle(ctx context.Context, job TransferJob) (string, string, int64, error) {
	if hasSourceBundle(job) && m.verifyManaged(ctx, job.BundlePath, job.BundleSHA256, job.BundleSize) {
		return job.BundlePath, job.BundleSHA256, job.BundleSize, nil
	}
	binary, err := m.openManagedFile(job.DownloadPath)
	if err != nil {
		return "", "", 0, errors.New("无法读取已下载的游戏附件")
	}
	defer binary.Close()
	source, err := m.openManagedFile(job.SourcePath)
	if err != nil {
		return "", "", 0, errors.New("无法读取已下载的对应版本源码")
	}
	defer source.Close()
	licenses, err := validateSourceZIP(ctx, source, job.SourceSize, job.Repo, job.SourceCommit)
	if err != nil {
		return "", "", 0, err
	}
	directory, err := m.sourceDirectory(job)
	if err != nil {
		return "", "", 0, err
	}
	defer directory.Close()
	name := bundleName(job)
	target := filepath.Join(m.downloadDir, job.ID, name)
	existing := false
	if info, err := directory.Lstat(name); err == nil {
		if !info.Mode().IsRegular() {
			return "", "", 0, errors.New("已有同名分享包不安全，原文件会保留")
		}
		existing = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", "", 0, err
	}
	partial := name + ".part-" + randomID()
	file, err := directory.OpenFile(partial, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0600)
	if err != nil {
		return "", "", 0, errors.New("无法创建含源码的分享包")
	}
	defer func() { file.Close(); directory.Remove(partial) }()
	writer := zip.NewWriter(file)
	addBytes := func(name string, data []byte) error {
		member, err := writer.CreateHeader(&zip.FileHeader{Name: name, Method: zip.Store})
		if err != nil {
			return err
		}
		_, err = member.Write(data)
		return err
	}
	addFile := func(name string, input *os.File, expected string, size int64) error {
		if _, err := input.Seek(0, io.SeekStart); err != nil {
			return err
		}
		member, err := writer.CreateHeader(&zip.FileHeader{Name: name, Method: zip.Store})
		if err != nil {
			return err
		}
		hash := sha256.New()
		n, err := io.Copy(&countingDownload{writer: io.MultiWriter(member, hash), ctx: ctx, progress: m.progress(job.ID), total: size}, io.LimitReader(input, size+1))
		if err != nil || n != size || hex.EncodeToString(hash.Sum(nil)) != expected {
			return errors.New("打包时文件发生变化，已保留原文件，请重新核对")
		}
		return nil
	}
	if err := addFile("game/"+job.Asset.Name, binary, job.SHA256, job.Asset.Size); err != nil {
		writer.Close()
		return "", "", 0, err
	}
	if err := addFile("source/"+sourceArchiveName(job), source, job.SourceSHA256, job.SourceSize); err != nil {
		writer.Close()
		return "", "", 0, err
	}
	// Stable entry order makes retries recover the same bytes after a crash.
	for _, name := range sortedLicenseNames(licenses) {
		if err := addBytes("licenses/"+name, licenses[name]); err != nil {
			writer.Close()
			return "", "", 0, err
		}
	}
	manifest := bundleManifest{Format: sourceBundleVersion, Repo: job.Repo, ProjectName: job.Name, GameNameZh: job.GameNameZh,
		GameNameOriginal: job.GameNameOriginal, Version: job.Version, Arch: job.Arch, SupportedSystems: job.SupportedSystems,
		ReleaseURL: job.Asset.URL, AssetName: job.Asset.Name, AssetSHA256: job.SHA256, SourceCommit: job.SourceCommit,
		SourceURL: job.SourceURL, SourceSHA256: job.SourceSHA256, Description: job.Description, Requirements: job.DataNote, Guide: job.Guide}
	encoded, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		writer.Close()
		return "", "", 0, err
	}
	if err := addBytes("manifest.json", encoded); err != nil {
		writer.Close()
		return "", "", 0, err
	}
	gameName := job.GameNameZh
	if gameName == "" {
		gameName = "中文游戏名待核实"
	}
	description := job.Description
	if description == "" {
		description = "中文简介待补充；请查看上游文档。"
	}
	instructions := fmt.Sprintf("PortShelf 游戏与源码分享包\n\n游戏：%s\n项目：%s\n仓库：https://github.com/%s\n版本：%s\n附件架构：Windows %s\n上游发布支持系统：%s\n\n%s\n\n运行说明：%s\n运行指南：%s\n\n目录说明：\n- game/：上游发布的原始游戏附件，原文件字节完整保留。\n- source/：发布标签对应提交的完整 GitHub 源码 ZIP；本工具不解压或执行。\n- licenses/：源码归档中的顶层许可与版权声明副本；完整原文仍保留在源码 ZIP 内。\n- manifest.json：版本、来源、提交与文件摘要。\n\n源码提交：%s\n源码来源：%s\n游戏附件 SHA-256：%s\n源码归档 SHA-256：%s\n\n源码归档保留 GitHub 提供的内容；子模块及 Git LFS 对象是否包含取决于上游归档设置，请依上游构建文档获取。\n部分移植需自备正版游戏数据，本包仅收录上游公开发布附件与源码，不补充原版游戏素材。\n游戏和源码适用上游各自的许可与版权声明，分发时应保留对应原文。\n", gameName, job.Name, job.Repo, job.Version, job.Arch, systemDescription(job.SupportedSystems), description, job.DataNote, job.Guide, job.SourceCommit, job.SourceURL, job.SHA256, job.SourceSHA256)
	if err := addBytes("使用说明.txt", []byte(instructions)); err != nil {
		writer.Close()
		return "", "", 0, err
	}
	if err := writer.Close(); err != nil {
		return "", "", 0, errors.New("分享包未完整写入")
	}
	if err := file.Sync(); err != nil {
		return "", "", 0, err
	}
	digest, size, err := hashFile(ctx, file, maxBundleBytes)
	if err != nil {
		return "", "", 0, err
	}
	if err := validateBundleZIP(ctx, file, size, job); err != nil {
		return "", "", 0, err
	}
	if err := file.Close(); err != nil {
		return "", "", 0, err
	}
	if existing {
		if !m.verifyManaged(ctx, target, digest, size) {
			return "", "", 0, errors.New("已有同名分享包与本次内容不一致，原文件会保留")
		}
	} else if err := directory.Rename(partial, name); err != nil {
		return "", "", 0, errors.New("无法保存完整分享包")
	}
	return target, digest, size, nil
}

func sortedLicenseNames(licenses map[string][]byte) []string {
	names := make([]string, 0, len(licenses))
	for name := range licenses {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func validateBundleZIP(ctx context.Context, file *os.File, size int64, job TransferJob) error {
	reader, err := zip.NewReader(file, size)
	if err != nil {
		return errors.New("分享包 ZIP 校验失败")
	}
	required := map[string]string{"game/" + job.Asset.Name: job.SHA256, "source/" + sourceArchiveName(job): job.SourceSHA256}
	found := map[string]bool{}
	for _, member := range reader.File {
		body, err := member.Open()
		if err != nil {
			return err
		}
		hash := sha256.New()
		n, err := io.Copy(&countingDownload{writer: hash, ctx: ctx, progress: func(int64, int64) {}}, io.LimitReader(body, maxBundleBytes+1))
		closeErr := body.Close()
		if err != nil || closeErr != nil || uint64(n) != member.UncompressedSize64 {
			return errors.New("分享包内容校验失败")
		}
		if expected, ok := required[member.Name]; ok {
			if found[member.Name] || hex.EncodeToString(hash.Sum(nil)) != expected {
				return errors.New("分享包内游戏或源码摘要不匹配")
			}
			found[member.Name] = true
		}
	}
	if len(found) != len(required) {
		return errors.New("分享包缺少游戏或源码文件")
	}
	return nil
}

func (m *transferManager) prepareSourceBundle(ctx context.Context, id string) error {
	job, _ := m.job(id)
	if len(job.Providers) == 0 {
		return nil
	}
	if hasSourceBundle(job) && (localFilesWereCleaned(job) && !m.needsLocalDownload(job) || m.verifyManaged(ctx, job.BundlePath, job.BundleSHA256, job.BundleSize)) {
		return nil
	}
	if err := m.stage(id, "source", ""); err != nil {
		return err
	}
	if job.SourceCommit == "" {
		commit, err := m.app.github.releaseCommit(ctx, job.Repo, job.Version)
		if err != nil {
			return err
		}
		if err := m.modify(id, func(j *TransferJob) { j.SourceCommit, j.SourceURL = commit, sourceArchiveURL(j.Repo, commit) }, true); err != nil {
			return err
		}
		job, _ = m.job(id)
	}
	sourcePath, sourceSHA, sourceSize, err := m.downloadSource(ctx, job)
	if err != nil {
		return err
	}
	if err := m.modify(id, func(j *TransferJob) { j.SourcePath, j.SourceSHA256, j.SourceSize = sourcePath, sourceSHA, sourceSize }, true); err != nil {
		return err
	}
	if err := m.stage(id, "bundle", ""); err != nil {
		return err
	}
	job, _ = m.job(id)
	bundlePath, bundleSHA, bundleSize, err := m.createSourceBundle(ctx, job)
	if err != nil {
		return err
	}
	return m.modify(id, func(j *TransferJob) {
		if j.BundleSHA256 != bundleSHA {
			for provider, output := range j.Outputs {
				if output.File.ID != "" || output.Share.URL != "" {
					if j.LegacyOutputs == nil {
						j.LegacyOutputs = map[string]TransferOutput{}
					}
					j.LegacyOutputs[provider] = output
				}
			}
			j.Outputs = map[string]TransferOutput{}
		}
		j.BundleVersion, j.BundlePath, j.BundleSHA256, j.BundleSize = sourceBundleVersion, bundlePath, bundleSHA, bundleSize
	}, true)
}
