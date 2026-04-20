(function () {
  const tabChat = document.getElementById("tab-chat");
  const tabHistory = document.getElementById("tab-history");
  const tabReport = document.getElementById("tab-report");
  const panelChat = document.getElementById("panel-chat");
  const panelHistory = document.getElementById("panel-history");
  const panelReport = document.getElementById("panel-report");

  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const btnSend = document.getElementById("btn-send");
  const thread = document.getElementById("chat-thread");
  const statusPill = document.getElementById("status-pill");
  const lastQuery = document.getElementById("last-query");

  const btnRefreshHistory = document.getElementById("btn-refresh-history");
  const historyList = document.getElementById("history-list");

  const btnGenerateMd = document.getElementById("btn-generate-md");
  const btnGeneratePdf = document.getElementById("btn-generate-pdf");
  const reportPreview = document.getElementById("report-preview");
  const downloadMd = document.getElementById("download-md");
  const downloadPdf = document.getElementById("download-pdf");

  function getSessionId() {
    const key = "chocolart_ai_session_id";
    let sid = localStorage.getItem(key);
    if (!sid) {
      sid = "sid_" + Math.random().toString(16).slice(2) + "_" + Date.now().toString(16);
      localStorage.setItem(key, sid);
    }
    return sid;
  }

  const sessionId = getSessionId();

  function setStatus(state) {
    statusPill.className = "pill " + state;
    const labels = { idle: "Listo", running: "Pensando…", ok: "Listo", err: "Error" };
    statusPill.textContent = labels[state] || state;
  }

  function setLoading(loading) {
    btnSend.disabled = loading;
    btnSend.querySelector(".btn-text").hidden = loading;
    btnSend.querySelector(".btn-spinner").hidden = !loading;
  }

  function setActiveTab(which) {
    const all = [
      { tab: tabChat, panel: panelChat, key: "chat" },
      { tab: tabHistory, panel: panelHistory, key: "history" },
      { tab: tabReport, panel: panelReport, key: "report" },
    ];
    for (const it of all) {
      const on = it.key === which;
      it.tab.classList.toggle("active", on);
      it.tab.setAttribute("aria-selected", on ? "true" : "false");
      it.panel.classList.toggle("active", on);
    }
  }

  tabChat.addEventListener("click", () => setActiveTab("chat"));
  tabHistory.addEventListener("click", () => {
    setActiveTab("history");
    refreshHistory();
  });
  tabReport.addEventListener("click", () => setActiveTab("report"));

  function addBubble(role, text) {
    const el = document.createElement("div");
    el.className = "bubble " + role;
    el.textContent = text;
    thread.appendChild(el);
    thread.scrollTop = thread.scrollHeight;
    return el;
  }

  function clearEphemeralSteps() {
    thread.querySelectorAll(".bubble.step").forEach((n) => n.remove());
  }

  async function sendMessage(message) {
    setStatus("running");
    setLoading(true);
    lastQuery.textContent = "—";
    lastQuery.classList.add("muted");
    clearEphemeralSteps();
    let liveStepEl = null;
    try {
      // Prefer streaming endpoint (shows verbose logs while running).
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }

      // Read SSE-like stream from POST response.
      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "";

      function showStep(text) {
        if (!text) return;
        if (liveStepEl && liveStepEl.isConnected) {
          liveStepEl.textContent = text;
        } else {
          liveStepEl = addBubble("step", text);
        }
        thread.scrollTop = thread.scrollHeight;
      }

      function handleResult(data) {
        clearEphemeralSteps();
        liveStepEl = null;
        if (!data || data.ok === false) {
          const errMsg = data && data.error ? data.error : "(sin detalle)";
          addBubble("ai", "Error: " + errMsg);
          setStatus("err");
          return;
        }

        addBubble("ai", data.ia_respuesta || "(sin respuesta)");
        if (data.query_generada) {
          lastQuery.textContent = data.query_generada;
          lastQuery.classList.remove("muted");
        }
        if (data.report_download_path) {
          if (data.report_format === "pdf") {
            downloadPdf.href = data.report_download_path;
            downloadPdf.hidden = false;
            downloadMd.hidden = true;
            reportPreview.textContent = "PDF generado. Usá el botón de descarga.";
            reportPreview.classList.remove("muted");
            setActiveTab("report");
          } else {
            if (data.report_md) {
              reportPreview.textContent = data.report_md;
              reportPreview.classList.remove("muted");
            }
            downloadMd.href = data.report_download_path;
            downloadMd.hidden = false;
            downloadPdf.hidden = true;
            setActiveTab("report");
          }
        }
        setStatus("ok");
      }

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // SSE events separated by blank line
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const rawEvent = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const lines = rawEvent.split("\n");
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const jsonText = line.slice(6);
            let evt;
            try {
              evt = JSON.parse(jsonText);
            } catch {
              continue;
            }
            if (evt.type === "step") showStep(evt.text || "");
            if (evt.type === "result") handleResult(evt);
          }
        }
      }
    } catch (err) {
      addBubble("ai", "Error: " + String(err.message || err));
      setStatus("err");
    } finally {
      setLoading(false);
      chatInput.focus();
    }
  }

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = (chatInput.value || "").trim();
    if (!msg) return;
    chatInput.value = "";
    addBubble("user", msg);
    await sendMessage(msg);
  });

  async function refreshHistory() {
    historyList.textContent = "Cargando…";
    historyList.classList.add("muted");
    try {
      const res = await fetch(`/api/chat/history?session_id=${encodeURIComponent(sessionId)}&limit=200`);
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const data = await res.json();
      historyList.textContent = JSON.stringify(data.items || [], null, 2);
      historyList.classList.remove("muted");
    } catch (err) {
      historyList.textContent = "Error: " + String(err.message || err);
      historyList.classList.remove("muted");
    }
  }

  btnRefreshHistory.addEventListener("click", refreshHistory);

  btnGenerateMd.addEventListener("click", async () => {
    reportPreview.textContent = "Generando…";
    reportPreview.classList.add("muted");
    downloadMd.hidden = true;
    try {
      const res = await fetch("/api/chat/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, format: "md" }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const data = await res.json();
      reportPreview.textContent = data.md || "(sin contenido)";
      reportPreview.classList.remove("muted");
      if (data.download_path) {
        downloadMd.href = data.download_path;
        downloadMd.hidden = false;
      }
      downloadPdf.hidden = true;
      setActiveTab("report");
    } catch (err) {
      reportPreview.textContent = "Error: " + String(err.message || err);
      reportPreview.classList.remove("muted");
    }
  });

  btnGeneratePdf.addEventListener("click", async () => {
    reportPreview.textContent = "Generando PDF…";
    reportPreview.classList.add("muted");
    downloadPdf.hidden = true;
    try {
      const res = await fetch("/api/chat/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, format: "pdf" }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const data = await res.json();
      reportPreview.textContent = "PDF generado. Usá el botón de descarga.";
      reportPreview.classList.remove("muted");
      if (data.download_path) {
        downloadPdf.href = data.download_path;
        downloadPdf.hidden = false;
      }
      setActiveTab("report");
    } catch (err) {
      reportPreview.textContent = "Error: " + String(err.message || err);
      reportPreview.classList.remove("muted");
    }
  });

  // Initial
  setActiveTab("chat");
  addBubble("ai", "Hola. ¿Qué querés consultar hoy?");
})();
