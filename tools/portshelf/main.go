package main

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

//go:embed web/* catalog.json snapshot.json
var assets embed.FS

var version = "1.2.0"
var errRunning = errors.New("PortShelf 已在运行")

func main() {
	if err := run(); err != nil {
		notifyUser("PortShelf 启动失败", err.Error())
		os.Exit(1)
	}
}

func run() error {
	noBrowser := flag.Bool("no-browser", false, "不自动打开浏览器")
	dataDir := flag.String("data-dir", "", "游戏列表与缓存保存目录")
	listen := flag.String("listen", "127.0.0.1:0", "仅支持 127.0.0.1，默认自动分配端口")
	flag.Parse()
	if *dataDir == "" {
		base, err := os.UserConfigDir()
		if err != nil {
			return err
		}
		if runtime.GOOS == "windows" && os.Getenv("LOCALAPPDATA") != "" {
			base = os.Getenv("LOCALAPPDATA")
		}
		*dataDir = filepath.Join(base, "PortShelf")
	}
	lib, err := newLibrary(*dataDir)
	if err != nil {
		return err
	}
	unlock, err := lockLibrary(lib.root)
	if errors.Is(err, errRunning) {
		if b, readErr := os.ReadFile(filepath.Join(lib.root, "session.url")); readErr == nil && !*noBrowser {
			sessionURL := strings.TrimSpace(string(b))
			if validSessionURL(sessionURL) {
				if err := openURL(sessionURL); err != nil {
					notifyUser("PortShelf", "自动打开浏览器失败，请复制此地址：\n"+sessionURL)
				}
			}
		}
		fmt.Println("PortShelf 已经运行，请查看浏览器中的游戏列表。")
		return nil
	}
	if err != nil {
		return err
	}
	defer unlock()
	host, _, err := net.SplitHostPort(*listen)
	if err != nil || host != "127.0.0.1" {
		return errors.New("仅允许监听 127.0.0.1")
	}
	ln, err := net.Listen("tcp", *listen)
	if err != nil {
		return err
	}
	defer ln.Close()
	app, err := newApp(lib)
	if err != nil {
		return err
	}
	defer app.cancel()
	app.host = ln.Addr().String()
	server := &http.Server{Handler: app.handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 60 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	sessionURL := "http://" + app.host + "/#" + app.token
	if err = os.WriteFile(filepath.Join(lib.root, "session.url"), []byte(sessionURL), 0600); err != nil {
		return err
	}
	defer os.Remove(filepath.Join(lib.root, "session.url"))
	fmt.Printf("PortShelf %s\n缓存目录：%s\n游戏列表：%s\n关闭工具可点击界面中的“退出工具”。\n", version, lib.root, sessionURL)
	interrupt := make(chan os.Signal, 1)
	signal.Notify(interrupt, os.Interrupt)
	defer signal.Stop(interrupt)
	shutdownDone := make(chan struct{})
	go func() {
		defer close(shutdownDone)
		select {
		case <-interrupt:
		case <-app.quit:
		case <-app.ctx.Done():
		}
		app.cancel()
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		_ = server.Shutdown(ctx)
	}()
	if !*noBrowser {
		go func() {
			if err := openURL(sessionURL); err != nil {
				notifyUser("PortShelf", "自动打开浏览器失败，请复制此地址：\n"+sessionURL)
			}
		}()
	}
	err = server.Serve(ln)
	app.cancel()
	<-shutdownDone
	if err != nil && !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}

var sessionTokenPattern = regexp.MustCompile(`^[a-f0-9]{48}$`)

func validSessionURL(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.User != nil || u.Path != "/" || u.RawQuery != "" || u.ForceQuery || !sessionTokenPattern.MatchString(u.Fragment) {
		return false
	}
	port, err := strconv.Atoi(u.Port())
	return err == nil && port > 0 && port <= 65535
}

func readCatalog() ([]Game, error) {
	b, err := assets.ReadFile("catalog.json")
	if err != nil {
		return nil, err
	}
	var games []Game
	if err := json.Unmarshal(b, &games); err != nil {
		return nil, err
	}
	for i := range games {
		if err := validateGame(&games[i]); err != nil {
			return nil, err
		}
	}
	return games, nil
}
