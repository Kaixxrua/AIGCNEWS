package main

import (
	"errors"
	"net/http"
	"os"
	"path/filepath"
)

func (a *App) registerAutomationRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/automation", func(w http.ResponseWriter, r *http.Request) {
		reply(w, http.StatusOK, a.automation.status())
	})
	mux.HandleFunc("POST /api/automation", func(w http.ResponseWriter, r *http.Request) {
		var config AutomationConfig
		if err := decode(w, r, &config); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		if _, err := validateAutomationConfig(config); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		if err := a.automation.configure(config); err != nil {
			fail(w, http.StatusInternalServerError, err)
			return
		}
		reply(w, http.StatusOK, a.automation.status())
	})
	mux.HandleFunc("POST /api/automation/run", func(w http.ResponseWriter, r *http.Request) {
		var body struct{}
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		if err := a.automation.requestRun(); err != nil {
			fail(w, http.StatusConflict, err)
			return
		}
		reply(w, http.StatusAccepted, a.automation.status())
	})
	mux.HandleFunc("POST /api/automation/open", func(w http.ResponseWriter, r *http.Request) {
		var body struct{}
		if err := decode(w, r, &body); err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		target := filepath.Join(a.lib.root, "exports")
		info, err := os.Lstat(target)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			fail(w, http.StatusNotFound, errors.New("导出目录尚未生成或不可用"))
			return
		}
		if err := openURL(target); err != nil {
			fail(w, http.StatusInternalServerError, errors.New("无法打开导出目录，请复制导出路径后在文件管理器中打开"))
			return
		}
		reply(w, http.StatusOK, map[string]bool{"ok": true})
	})
}
