(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const fields = [
    "nativeAppKey",
    "nativeAppSecret",
    "nativeAppCode",
    "loginAppCode",
  ];
  const state = {
    selectedPath: "",
    result: null,
    visible: false,
    ready: false,
    toastTimer: null,
  };

  const els = {
    pickButton: $("#pick-button"),
    extractButton: $("#extract-button"),
    fileName: $("#file-name"),
    fileDetail: $("#file-detail"),
    apkPath: $("#apk-path"),
    status: $("#status-message"),
    errorPanel: $("#error-panel"),
    errorText: $("#error-text"),
    resultPanel: $("#result-panel"),
    resultFile: $("#result-file"),
    fieldList: $("#field-list"),
    toggleVisibility: $("#toggle-visibility"),
    copyAll: $("#copy-all"),
    toast: $("#toast"),
  };

  function setStatus(message, kind = "") {
    els.status.textContent = message;
    els.status.classList.toggle("is-error", kind === "error");
    els.status.classList.toggle("is-ok", kind === "ok");
  }

  function showToast(message) {
    window.clearTimeout(state.toastTimer);
    els.toast.textContent = message;
    els.toast.classList.add("is-visible");
    state.toastTimer = window.setTimeout(() => {
      els.toast.classList.remove("is-visible");
    }, 1800);
  }

  function formatSize(bytes) {
    if (!Number.isFinite(bytes)) return "";
    if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
    if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  }

  function setReady(ready) {
    state.ready = ready;
    els.pickButton.disabled = !ready;
    els.extractButton.disabled = !ready || !state.selectedPath;
    setStatus(
      ready ? "桌面组件已就绪，请选择领克 4.3.x APK。" : "正在连接桌面应用…"
    );
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.append(helper);
      helper.select();
      document.execCommand("copy");
      helper.remove();
    }
  }

  function renderResult(result) {
    state.result = result;
    state.visible = false;
    els.errorPanel.hidden = true;
    els.resultPanel.hidden = false;
    els.toggleVisibility.textContent = "显示明文";
    els.resultFile.textContent = `${result.file.name} · ${formatSize(result.file.size)}`;
    els.fieldList.replaceChildren();

    fields.forEach((name) => {
      const row = document.createElement("div");
      row.className = "field-row";
      const label = document.createElement("span");
      label.className = "field-name";
      label.textContent = name;
      const value = document.createElement("code");
      value.className = "field-value is-hidden";
      value.textContent = result.fields[name];
      const button = document.createElement("button");
      button.className = "copy-one";
      button.type = "button";
      button.textContent = "复制";
      button.addEventListener("click", async () => {
        await copyText(result.fields[name]);
        showToast(`${name} 已复制`);
      });
      row.append(label, value, button);
      els.fieldList.append(row);
    });
  }

  function renderError(message) {
    els.resultPanel.hidden = true;
    els.errorPanel.hidden = false;
    els.errorText.textContent = message;
    setStatus("提取失败，请查看下方原因。", "error");
  }

  async function chooseFile() {
    if (!state.ready) return;
    els.pickButton.disabled = true;
    try {
      const picked = await window.pywebview.api.pick_apk();
      if (!picked.ok) {
        if (!picked.cancelled) renderError(picked.error || "无法选择文件");
        return;
      }
      state.selectedPath = picked.path;
      els.apkPath.value = picked.path;
      const name = picked.path.split(/[\\/]/).pop();
      els.fileName.textContent = name;
      els.fileDetail.textContent = "已选择，正在读取 KeyVault…";
      els.extractButton.disabled = false;
      await extractSelected();
    } catch (error) {
      renderError(error.message || "无法打开文件选择器");
    } finally {
      els.pickButton.disabled = !state.ready;
    }
  }

  async function extractSelected() {
    if (!state.ready) {
      setStatus("请通过 desktop/main.py 启动桌面应用。", "error");
      return;
    }
    const path = els.apkPath.value.trim() || state.selectedPath;
    if (!path) {
      setStatus("请先选择 APK 或填写完整路径。", "error");
      return;
    }
    state.selectedPath = path;
    els.extractButton.disabled = true;
    els.errorPanel.hidden = true;
    setStatus("正在离线解析 KeyVault…");
    try {
      const result = await window.pywebview.api.extract(path);
      if (!result.ok) {
        renderError(result.error || "提取失败");
        return;
      }
      const name = result.file.name;
      els.fileName.textContent = name;
      els.fileDetail.textContent = `${formatSize(result.file.size)} · 4 个字段已提取`;
      renderResult(result);
      setStatus("提取成功。请复制 4 个字段到 NAS 管理页。", "ok");
    } catch (error) {
      renderError(error.message || "提取过程发生异常");
    } finally {
      els.extractButton.disabled = !state.ready || !state.selectedPath;
    }
  }

  function toggleVisibility() {
    state.visible = !state.visible;
    els.toggleVisibility.textContent = state.visible ? "隐藏明文" : "显示明文";
    document.querySelectorAll(".field-value").forEach((element) => {
      element.classList.toggle("is-hidden", !state.visible);
    });
  }

  async function copyAll() {
    if (!state.result) return;
    const text = fields
      .map((name) => `${name}=${state.result.fields[name]}`)
      .join("\n");
    await copyText(text);
    showToast("4 个字段已全部复制");
  }

  function handlePathInput() {
    state.selectedPath = els.apkPath.value.trim();
    els.extractButton.disabled = !state.ready || !state.selectedPath;
    if (state.selectedPath) {
      const name = state.selectedPath.split(/[\\/]/).pop();
      els.fileName.textContent = name;
      els.fileDetail.textContent = "路径已填写，等待提取";
    }
  }

  els.pickButton.addEventListener("click", chooseFile);
  els.extractButton.addEventListener("click", extractSelected);
  els.apkPath.addEventListener("input", handlePathInput);
  els.apkPath.addEventListener("keydown", (event) => {
    if (event.key === "Enter") extractSelected();
  });
  els.toggleVisibility.addEventListener("click", toggleVisibility);
  els.copyAll.addEventListener("click", copyAll);

  window.addEventListener("pywebviewready", () => setReady(true));
  if (window.pywebview && window.pywebview.api) setReady(true);
})();
