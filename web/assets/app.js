(function () {
  const form = document.getElementById("run-form");
  const topic = document.getElementById("topic");
  const currentYear = document.getElementById("current_year");
  const btnStart = document.getElementById("btn-start");
  const btnClear = document.getElementById("btn-clear");
  const logEl = document.getElementById("log");
  const statusPill = document.getElementById("status-pill");
  const resultFinal = document.getElementById("result-final");
  const resultReport = document.getElementById("result-report");

  const defaultYear = String(new Date().getFullYear());
  if (!currentYear.value) currentYear.value = defaultYear;

  function setStatus(state) {
    statusPill.className = "pill " + state;
    const labels = { idle: "Listo", running: "Ejecutando…", ok: "Completado", err: "Error" };
    statusPill.textContent = labels[state] || state;
  }

  function setLoading(loading) {
    btnStart.disabled = loading;
    btnStart.querySelector(".btn-text").hidden = loading;
    btnStart.querySelector(".btn-spinner").hidden = !loading;
  }

  btnClear.addEventListener("click", () => {
    logEl.textContent = "";
  });

  async function parseSSEStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const block of parts) {
        const line = block.trim();
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.slice(5).trim();
        try {
          const data = JSON.parse(jsonStr);
          if (data.type === "log" && data.text) {
            logEl.textContent += data.text;
            logEl.scrollTop = logEl.scrollHeight;
          } else if (data.type === "result") {
            return data;
          }
        } catch (_) {
          logEl.textContent += "\n[parse error]\n";
        }
      }
    }
    return null;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    logEl.textContent = "";
    resultFinal.textContent = "Esperando resultado…";
    resultFinal.classList.add("muted");
    resultReport.textContent = "Generando informe…";
    resultReport.classList.add("muted");
    setStatus("running");
    setLoading(true);

    try {
      const res = await fetch("/api/run/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          topic: topic.value.trim(),
          current_year: currentYear.value.trim(),
        }),
      });

      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }

      const data = await parseSSEStream(res);
      if (!data) {
        setStatus("err");
        resultFinal.textContent = "No se recibió resultado del servidor.";
        resultFinal.classList.remove("muted");
        return;
      }

      if (data.ok) {
        setStatus("ok");
        resultFinal.textContent = data.final_output || "(Sin texto de salida explícito.)";
        resultFinal.classList.remove("muted");
        if (data.report_md) {
          resultReport.textContent = data.report_md;
          resultReport.classList.remove("muted");
        } else {
          resultReport.textContent = "No se encontró output/report.md.";
          resultReport.classList.add("muted");
        }
      } else {
        setStatus("err");
        resultFinal.textContent = data.error || "Error desconocido.";
        resultFinal.classList.remove("muted");
        if (data.report_md) {
          resultReport.textContent = data.report_md;
          resultReport.classList.remove("muted");
        }
      }
    } catch (err) {
      setStatus("err");
      resultFinal.textContent = String(err.message || err);
      resultFinal.classList.remove("muted");
      resultReport.textContent = "—";
      resultReport.classList.add("muted");
    } finally {
      setLoading(false);
    }
  });
})();
