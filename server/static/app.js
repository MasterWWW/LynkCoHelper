(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const state = {
    sid: "",
    validating: false,
    running: false,
    runRequestInFlight: false,
    toastTimer: null,
    pollTimer: null,
  };

  const els = {
    apiToken: $("#api-token"),
    saveToken: $("#save-token"),
    systemBadge: $("#system-badge"),
    systemBadgeText: $("#system-badge-text"),
    metricSecrets: $("#metric-secrets"),
    metricSecretsDetail: $("#metric-secrets-detail"),
    metricLogin: $("#metric-login"),
    metricLoginDetail: $("#metric-login-detail"),
    metricLastRun: $("#metric-last-run"),
    metricLastRunDetail: $("#metric-last-run-detail"),
    metricNextRun: $("#metric-next-run"),
    metricScheduleDetail: $("#metric-schedule-detail"),
    secretsForm: $("#secrets-form"),
    secretsBadge: $("#secrets-badge"),
    secretsPills: $("#secrets-pills"),
    loginBadge: $("#login-badge"),
    loginStartForm: $("#login-start-form"),
    phone: $("#phone"),
    sliderStage: $("#slider-stage"),
    sliderState: $("#slider-state"),
    geetestFrame: $("#geetest-frame"),
    restartLogin: $("#restart-login"),
    smsForm: $("#sms-form"),
    smsCode: $("#sms-code"),
    loginMessage: $("#login-message"),
    runButton: $("#run-button"),
    runBadge: $("#run-badge"),
    runMessage: $("#run-message"),
    reportPanel: $("#report-panel"),
    reportSummary: $("#report-summary"),
    reportMetrics: $("#report-metrics"),
    reportSign: $("#report-sign"),
    reportTasks: $("#report-tasks"),
    toast: $("#toast"),
  };

  const FIELD_LABELS = {
    nativeAppKey: "nativeAppKey",
    nativeAppSecret: "nativeAppSecret",
    nativeAppCode: "nativeAppCode",
    loginAppCode: "loginAppCode",
  };

  const STATUS_LABELS = {
    valid: "有效",
    expired: "已过期",
    unknown: "已配置",
    missing: "未配置",
  };

  function storedToken() {
    return localStorage.getItem("lynkcoApiToken") || "";
  }

  function setBusy(button, busy) {
    if (!button) return;
    button.disabled = busy;
    button.classList.toggle("is-busy", busy);
  }

  function showToast(message, isError = false) {
    window.clearTimeout(state.toastTimer);
    els.toast.textContent = message;
    els.toast.classList.toggle("is-error", isError);
    els.toast.classList.add("is-visible");
    state.toastTimer = window.setTimeout(() => {
      els.toast.classList.remove("is-visible");
    }, 3200);
  }

  function setMessage(element, message, kind = "") {
    element.textContent = message || "";
    element.classList.toggle("is-error", kind === "error");
    element.classList.toggle("is-ok", kind === "ok");
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = storedToken();
    if (token) headers.set("X-API-Token", token);
    if (options.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, {
      ...options,
      headers,
      cache: "no-store",
    });
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
      const error = new Error(
        typeof data === "object" && data && data.detail
          ? data.detail
          : `请求失败（HTTP ${response.status}）`
      );
      error.status = response.status;
      error.payload = data;
      if (response.status === 401) {
        showToast("访问令牌无效，请在右上角重新填写", true);
        els.apiToken.focus();
      }
      throw error;
    }
    return data;
  }

  function formatTime(value, fallback = "—") {
    if (!value) return fallback;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }

  function statusPill(element, text, kind = "") {
    element.textContent = text;
    element.classList.remove("is-ok", "is-error", "is-warning");
    if (kind) element.classList.add(kind);
  }

  function renderSecretPills(configured = {}) {
    els.secretsPills.replaceChildren();
    Object.entries(FIELD_LABELS).forEach(([field, label]) => {
      const pill = document.createElement("span");
      pill.className = `field-pill ${configured[field] ? "is-ok" : ""}`.trim();
      pill.textContent = `${label} · ${configured[field] ? "已配置" : "缺失"}`;
      els.secretsPills.append(pill);
    });
  }

  function renderStatus(data) {
    const configuredCount = Object.values(data.secretsConfigured || {}).filter(Boolean).length;
    els.metricSecrets.textContent = `${configuredCount}/4`;
    els.metricSecretsDetail.textContent = data.secretsComplete ? "密钥已配齐" : "仍有字段缺失";
    statusPill(
      els.secretsBadge,
      data.secretsComplete ? "已配齐" : "未配齐",
      data.secretsComplete ? "is-ok" : "is-warning"
    );
    renderSecretPills(data.secretsConfigured);

    const loginStatus = data.hasRefreshToken ? data.refreshTokenStatus : "missing";
    els.metricLogin.textContent = STATUS_LABELS[loginStatus] || "未知";
    els.metricLoginDetail.textContent = data.hasRefreshToken
      ? "refreshToken 已持久化"
      : "请完成一次网页登录";
    statusPill(
      els.loginBadge,
      STATUS_LABELS[loginStatus] || "未知",
      loginStatus === "valid" || loginStatus === "unknown"
        ? "is-ok"
        : loginStatus === "missing"
          ? ""
          : "is-warning"
    );

    const last = data.lastRun;
    if (last) {
      const statusText = {
        success: "成功",
        partial: "部分成功",
        failed: "失败",
      }[last.status] || "已运行";
      els.metricLastRun.textContent = statusText;
      els.metricLastRunDetail.textContent = formatTime(last.finishedAt || last.startedAt);
      statusPill(
        $("#run-badge"),
        data.schedule.running ? "运行中" : statusText,
        last.status === "success" ? "is-ok" : last.status === "failed" ? "is-error" : "is-warning"
      );
    } else {
      els.metricLastRun.textContent = "暂无";
      els.metricLastRunDetail.textContent = "尚未执行打卡";
      statusPill($("#run-badge"), data.schedule.running ? "运行中" : "空闲");
    }

    if (data.schedule.error) {
      els.metricNextRun.textContent = "调度异常";
      els.metricScheduleDetail.textContent = data.schedule.error;
      els.systemBadge.className = "system-badge is-warning";
      els.systemBadgeText.textContent = "服务在线 · 调度需检查";
    } else if (data.schedule.nextRun) {
      els.metricNextRun.textContent = formatTime(data.schedule.nextRun);
      els.metricScheduleDetail.textContent = `${data.schedule.cron} · ${data.schedule.timezone}`;
      els.systemBadge.className = "system-badge is-ready";
      els.systemBadgeText.textContent = "服务在线 · 自动打卡已启用";
    } else if (data.schedule.enabled) {
      els.metricNextRun.textContent = "已启用";
      els.metricScheduleDetail.textContent = `${data.schedule.cron} · ${data.schedule.timezone}`;
      els.systemBadge.className = "system-badge is-ready";
      els.systemBadgeText.textContent = "服务在线";
    } else {
      els.metricNextRun.textContent = "未启用";
      els.metricScheduleDetail.textContent = "检查调度配置";
      els.systemBadge.className = "system-badge is-warning";
      els.systemBadgeText.textContent = "服务在线 · 调度未启用";
    }

    if (data.schedule.running) {
      statusPill(els.runBadge, "运行中", "is-warning");
      setRunBusy(true);
    } else if (!state.runRequestInFlight) {
      setRunBusy(false);
    }
  }

  function renderReport(report) {
    if (!report) {
      els.reportPanel.hidden = true;
      return;
    }
    els.reportPanel.hidden = false;
    els.reportSummary.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = {
      success: "本次执行成功",
      partial: "签到完成，分享未完全成功",
      failed: "本次执行失败",
    }[report.status] || "执行结果";
    const trigger = document.createElement("span");
    trigger.textContent = report.trigger === "scheduled" ? "定时任务" : "手动执行";
    const time = document.createElement("span");
    time.textContent = formatTime(report.finishedAt || report.startedAt);
    els.reportSummary.append(title, trigger, time);

    els.reportMetrics.replaceChildren();
    const energyBefore = report.energy?.before ?? "?";
    const energyAfter = report.energy?.after ?? "?";
    const delta = report.energy?.delta;
    const metrics = [
      ["积分", `${energyBefore} → ${energyAfter}`, delta == null ? "" : `${delta >= 0 ? "+" : ""}${delta}`],
      ["连续签到", report.continueDays == null ? "—" : `${report.continueDays} 天`, report.signCardNumber == null ? "" : `签到卡 ${report.signCardNumber}`],
      ["成长值", growthText(report.growth?.after), growthText(report.growth?.before, true)],
    ];
    metrics.forEach(([label, value, detail]) => {
      const card = document.createElement("div");
      card.className = "report-metric";
      const labelEl = document.createElement("span");
      labelEl.textContent = label;
      const valueEl = document.createElement("strong");
      valueEl.textContent = value;
      card.append(labelEl, valueEl);
      if (detail) {
        const detailEl = document.createElement("span");
        detailEl.textContent = detail;
        card.append(detailEl);
      }
      els.reportMetrics.append(card);
    });

    els.reportSign.replaceChildren();
    addDetail("签到", report.alreadySigned ? "今日已签到" : report.sign?.ok ? "成功" : "失败");
    if (report.sign?.rewardEnergy != null) addDetail("签到奖励", `+${report.sign.rewardEnergy} 能量体`);
    addDetail("分享", report.share == null
      ? "未执行"
      : report.share.ok
        ? "上报成功"
        : `失败：${report.share.message || "详情见服务日志"}`);
    if (report.share?.articleTitle) addDetail("分享文章", report.share.articleTitle);
    if (report.sign?.message) addDetail("签到信息", report.sign.message);
    if (report.error) addDetail("错误", report.error);

    els.reportTasks.replaceChildren();
    if (Array.isArray(report.tasks) && report.tasks.length) {
      report.tasks.forEach((task) => {
        const item = document.createElement("li");
        item.textContent = `${task.name}：${task.process}（${task.reward}）`;
        els.reportTasks.append(item);
      });
    } else {
      const item = document.createElement("li");
      item.textContent = "暂无任务进度数据";
      els.reportTasks.append(item);
    }
  }

  function growthText(growth, withLabel = false) {
    if (!growth || (growth.name == null && growth.value == null)) return "—";
    const text = [growth.name, growth.value].filter((value) => value != null && value !== "").join(" / ");
    return withLabel ? `之前 ${text}` : text;
  }

  function addDetail(label, value) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value == null || value === "" ? "—" : String(value);
    row.append(term, description);
    els.reportSign.append(row);
  }

  function setRunBusy(busy) {
    state.running = busy;
    setBusy(els.runButton, busy);
    els.runButton.classList.toggle("is-busy", busy);
    els.runButton.querySelector(".button-label").textContent = busy ? "正在执行" : "立即签到";
  }

  async function refreshStatus() {
    try {
      const [status, reportData] = await Promise.all([api("/status"), api("/report")]);
      renderStatus(status);
      if (status.lastRun) {
        renderReport(reportData.report || status.lastRun);
      }
    } catch (error) {
      els.systemBadge.className = "system-badge is-warning";
      els.systemBadgeText.textContent = "无法读取状态";
      if (error.status !== 401) showToast(error.message, true);
    }
  }

  async function startLogin(event) {
    event.preventDefault();
    const phone = els.phone.value.trim();
    if (!phone) return;
    const button = els.loginStartForm.querySelector("button");
    setBusy(button, true);
    setMessage(els.loginMessage, "正在获取滑块配置…");
    els.smsForm.hidden = true;
    state.sid = "";
    try {
      const data = await api("/login/start", {
        method: "POST",
        body: JSON.stringify({ phone }),
      });
      state.sid = data.sid;
      els.sliderStage.hidden = false;
      els.sliderState.textContent = "正在加载极验…";
      const htmlResponse = await fetch(data.htmlUrl, {
        headers: storedToken() ? { "X-API-Token": storedToken() } : {},
        cache: "no-store",
      });
      if (!htmlResponse.ok) {
        let detail = `加载滑块失败（HTTP ${htmlResponse.status}）`;
        try {
          const payload = await htmlResponse.json();
          detail = payload.detail || detail;
        } catch (_) {
          // Non-JSON error body; the status-based message is enough.
        }
        throw new Error(detail);
      }
      const html = await htmlResponse.text();
      els.geetestFrame.srcdoc = html;
      els.sliderStage.scrollIntoView({ behavior: "smooth", block: "center" });
      setMessage(els.loginMessage, "请在内嵌页面完成滑块，成功后会自动继续。", "ok");
    } catch (error) {
      els.sliderStage.hidden = true;
      setMessage(els.loginMessage, error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  async function handleGeetestMessage(event) {
    if (event.origin !== window.location.origin) return;
    const message = event.data;
    if (!message || message.type !== "geetest-result" || state.validating || !state.sid) return;
    const payload = message.payload || {};
    if (!payload.lotNumber || !payload.captchaOutput || !payload.passToken || !payload.genTime) return;

    state.validating = true;
    els.sliderState.textContent = "正在校验并发送短信…";
    setMessage(els.loginMessage, "滑块已完成，正在校验…");
    try {
      await api("/login/validate", {
        method: "POST",
        body: JSON.stringify({
          sid: state.sid,
          lotNumber: payload.lotNumber,
          captchaOutput: payload.captchaOutput,
          passToken: payload.passToken,
          genTime: payload.genTime,
        }),
      });
      els.sliderStage.hidden = true;
      els.smsForm.hidden = false;
      els.smsCode.focus();
      setMessage(els.loginMessage, "短信验证码已发送，请输入后完成登录。", "ok");
    } catch (error) {
      els.sliderState.textContent = "校验失败，请重新获取滑块";
      setMessage(els.loginMessage, error.message, "error");
    } finally {
      state.validating = false;
    }
  }

  async function completeLogin(event) {
    event.preventDefault();
    if (!state.sid) {
      setMessage(els.loginMessage, "登录会话已失效，请重新开始。", "error");
      return;
    }
    const button = els.smsForm.querySelector("button");
    setBusy(button, true);
    setMessage(els.loginMessage, "正在完成登录…");
    try {
      await api("/login/complete", {
        method: "POST",
        body: JSON.stringify({ sid: state.sid, code: els.smsCode.value.trim() }),
      });
      state.sid = "";
      els.smsForm.reset();
      els.smsForm.hidden = true;
      els.loginStartForm.reset();
      setMessage(els.loginMessage, "登录成功，refreshToken 已写入持久化配置。", "ok");
      showToast("登录完成");
      await refreshStatus();
    } catch (error) {
      setMessage(els.loginMessage, error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  function restartLogin() {
    state.sid = "";
    state.validating = false;
    els.sliderStage.hidden = true;
    els.smsForm.hidden = true;
    els.geetestFrame.removeAttribute("srcdoc");
    setMessage(els.loginMessage, "已重置，请重新点击“获取滑块”。");
  }

  async function saveSecrets(event) {
    event.preventDefault();
    const form = new FormData(els.secretsForm);
    const body = Object.fromEntries(form.entries());
    const button = els.secretsForm.querySelector("button");
    setBusy(button, true);
    try {
      await api("/secrets", {
        method: "POST",
        body: JSON.stringify(body),
      });
      els.secretsForm.reset();
      showToast("密钥已保存到挂载卷");
      await refreshStatus();
    } catch (error) {
      showToast(error.message, true);
    } finally {
      setBusy(button, false);
    }
  }

  async function runNow() {
    if (state.running || state.runRequestInFlight) return;
    state.runRequestInFlight = true;
    setRunBusy(true);
    setMessage(els.runMessage, "正在签到与分享，请保持页面打开…");
    try {
      const report = await api("/run", { method: "POST" });
      renderReport(report);
      setMessage(
        els.runMessage,
        report.status === "success" ? "本次执行完成。" : "执行完成，请查看结果详情。",
        report.status === "success" ? "ok" : ""
      );
      showToast("每日任务执行完成");
    } catch (error) {
      if (error.status === 409) {
        setMessage(els.runMessage, "已有任务正在运行，请稍后再试。", "error");
      } else {
        const report = error.payload?.report;
        if (report) renderReport(report);
        setMessage(els.runMessage, error.message, "error");
      }
    } finally {
      state.runRequestInFlight = false;
      setRunBusy(false);
      await refreshStatus();
    }
  }

  function saveToken() {
    const token = els.apiToken.value.trim();
    if (token) localStorage.setItem("lynkcoApiToken", token);
    else localStorage.removeItem("lynkcoApiToken");
    showToast(token ? "访问令牌已保存在本机浏览器" : "已清除本机访问令牌");
  }

  els.apiToken.value = storedToken();
  els.saveToken.addEventListener("click", saveToken);
  els.secretsForm.addEventListener("submit", saveSecrets);
  els.loginStartForm.addEventListener("submit", startLogin);
  els.smsForm.addEventListener("submit", completeLogin);
  els.restartLogin.addEventListener("click", restartLogin);
  els.runButton.addEventListener("click", runNow);
  window.addEventListener("message", handleGeetestMessage);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshStatus();
  });

  refreshStatus();
  state.pollTimer = window.setInterval(() => {
    if (!document.hidden) refreshStatus();
  }, 30000);
})();
