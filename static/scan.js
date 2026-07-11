(function () {
  const root = document.getElementById("scanner-app");
  if (!root) {
    return;
  }

  const previewUrl = root.dataset.previewUrl;
  const gradeUrl = root.dataset.gradeUrl;
  const sheetRatio = Number(root.dataset.sheetRatio || "0.69");

  const video = root.querySelector('[data-role="camera-video"]');
  const overlay = root.querySelector('[data-role="camera-overlay"]');
  const placeholder = root.querySelector('[data-role="camera-placeholder"]');
  const flash = root.querySelector('[data-role="camera-flash"]');
  const resultPanel = root.querySelector('[data-role="scan-result"]');
  const resultSummary = root.querySelector('[data-role="result-summary"]');
  const resultContent = root.querySelector('[data-role="result-content"]');
  const resultTitle = root.querySelector('[data-role="result-title"]');
  const resultSubtitle = root.querySelector('[data-role="result-subtitle"]');
  const statusTitle = root.querySelector('[data-role="status-title"]');
  const statusText = root.querySelector('[data-role="status-text"]');

  const metricDetected = root.querySelector('[data-role="metric-detected"]');
  const metricConfidence = root.querySelector('[data-role="metric-confidence"]');
  const metricSharpness = root.querySelector('[data-role="metric-sharpness"]');
  const metricCoverage = root.querySelector('[data-role="metric-coverage"]');
  const metricStability = root.querySelector('[data-role="metric-stability"]');

  const startButton = root.querySelector('[data-action="start-camera"]');
  const captureButton = root.querySelector('[data-action="capture-now"]');
  const resumeButton = root.querySelector('[data-action="resume-scan"]');

  const previewCanvas = document.createElement("canvas");
  const fullCanvas = document.createElement("canvas");

  const state = {
    stream: null,
    previewTimer: null,
    previewBusy: false,
    gradeBusy: false,
    autoPaused: false,
    started: false,
    lastCorners: null,
    stableFrames: 0,
    flashTimer: null,
    lastCapturePreview: "",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function canvasToBlob(canvas, type, quality) {
    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) {
          resolve(blob);
          return;
        }
        reject(new Error("Khong tao duoc anh tu camera."));
      }, type, quality);
    });
  }

  function setStatus(title, text, tone) {
    statusTitle.textContent = title;
    statusText.textContent = text;
    root.dataset.stateTone = tone || "neutral";
  }

  function resetMetrics() {
    metricDetected.textContent = "Chưa";
    metricConfidence.textContent = "0%";
    metricSharpness.textContent = "-";
    metricCoverage.textContent = "-";
    metricStability.textContent = "0%";
  }

  function updateMetrics(preview) {
    metricDetected.textContent = preview.detected ? "Có" : "Chưa";
    metricConfidence.textContent = `${Math.round((preview.metrics?.confidence || 0) * 100)}%`;
    metricSharpness.textContent = preview.metrics?.sharpness ?? "-";
    metricCoverage.textContent = preview.metrics?.coverage ? `${Math.round(preview.metrics.coverage * 100)}%` : "-";
    metricStability.textContent = `${Math.min(state.stableFrames * 25, 100)}%`;
  }

  function resizeOverlay() {
    const rect = video.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    overlay.width = Math.max(1, Math.round(rect.width * ratio));
    overlay.height = Math.max(1, Math.round(rect.height * ratio));
    overlay.style.width = `${rect.width}px`;
    overlay.style.height = `${rect.height}px`;
  }

  function drawGuide(preview) {
    resizeOverlay();
    const ctx = overlay.getContext("2d");
    const width = overlay.width;
    const height = overlay.height;

    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

    const cssWidth = overlay.clientWidth;
    const cssHeight = overlay.clientHeight;
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    const polygon = (preview.corners || []).map((point) => ({
      x: point.x * cssWidth,
      y: point.y * cssHeight,
    }));

    if (!polygon.length) {
      const guide = guideRect(cssWidth, cssHeight);
      ctx.strokeStyle = "rgba(255,255,255,0.92)";
      ctx.lineWidth = 3;
      ctx.setLineDash([12, 10]);
      ctx.strokeRect(guide.x, guide.y, guide.width, guide.height);
      ctx.fillStyle = "rgba(0, 0, 0, 0.22)";
      ctx.fillRect(0, 0, cssWidth, cssHeight);
      ctx.clearRect(guide.x, guide.y, guide.width, guide.height);
      ctx.restore();
      return;
    }

    const stroke = preview.ready ? "#4bc36d" : "#ffcc55";
    ctx.fillStyle = "rgba(0, 0, 0, 0.22)";
    ctx.beginPath();
    ctx.rect(0, 0, cssWidth, cssHeight);
    ctx.moveTo(polygon[0].x, polygon[0].y);
    polygon.forEach((point) => ctx.lineTo(point.x, point.y));
    ctx.closePath();
    ctx.fill("evenodd");

    ctx.setLineDash([]);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(polygon[0].x, polygon[0].y);
    polygon.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
    ctx.closePath();
    ctx.stroke();

    polygon.forEach((point) => {
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = stroke;
      ctx.beginPath();
      ctx.arc(point.x, point.y, 3, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.restore();
  }

  function guideRect(width, height) {
    const maxHeight = height * 0.84;
    const maxWidth = width * 0.78;
    let guideHeight = maxHeight;
    let guideWidth = guideHeight * sheetRatio;

    if (guideWidth > maxWidth) {
      guideWidth = maxWidth;
      guideHeight = guideWidth / Math.max(sheetRatio, 0.1);
    }

    return {
      x: (width - guideWidth) / 2,
      y: (height - guideHeight) / 2,
      width: guideWidth,
      height: guideHeight,
    };
  }

  function cornerDelta(current, previous) {
    if (!current || !previous || current.length !== previous.length) {
      return Number.POSITIVE_INFINITY;
    }
    let sum = 0;
    for (let index = 0; index < current.length; index += 1) {
      sum += Math.abs(current[index].x - previous[index].x) + Math.abs(current[index].y - previous[index].y);
    }
    return sum / current.length;
  }

  function updateStability(preview) {
    if (!preview.detected || !preview.corners?.length) {
      state.lastCorners = null;
      state.stableFrames = 0;
      return false;
    }

    const delta = cornerDelta(preview.corners, state.lastCorners);
    state.lastCorners = preview.corners;

    if (delta < 0.02) {
      state.stableFrames = Math.min(state.stableFrames + 1, 4);
    } else {
      state.stableFrames = preview.ready ? 1 : 0;
    }
    return preview.ready && state.stableFrames >= 4;
  }

  function currentAnswerFormData() {
    const form = new FormData();
    form.append("section1", document.querySelector('[name="section1"]')?.value || "");
    form.append("section2", document.querySelector('[name="section2"]')?.value || "");
    form.append("section3", document.querySelector('[name="section3"]')?.value || "");
    return form;
  }

  function flashCapture() {
    flash.classList.add("active");
    window.clearTimeout(state.flashTimer);
    state.flashTimer = window.setTimeout(() => {
      flash.classList.remove("active");
    }, 240);
  }

  function schedulePreview(delay) {
    window.clearTimeout(state.previewTimer);
    if (!state.started || state.gradeBusy || state.autoPaused) {
      return;
    }
    state.previewTimer = window.setTimeout(runPreview, delay ?? 420);
  }

  function showCapturedFrame(previewSrc, title, text) {
    resultPanel.hidden = false;
    resultTitle.textContent = title;
    resultSubtitle.textContent = text;
    resultSummary.innerHTML = `
      <div class="capture-review">
        <article class="surface capture-card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Ảnh vừa chụp</p>
              <h2>Frame sẽ đem đi trải phẳng và chấm</h2>
            </div>
          </div>
          <div class="capture-thumb-frame">
            <img class="capture-thumb" src="${previewSrc}" alt="Ảnh camera vừa chụp">
          </div>
        </article>
        <article class="surface capture-card scan-pending">
          <div class="section-head">
            <div>
              <p class="eyebrow">Tiến trình</p>
              <h2>${escapeHtml(title)}</h2>
            </div>
          </div>
          <div class="pending-steps">
            <div class="pending-step active">1. Đã chụp frame từ camera</div>
            <div class="pending-step active">2. Đang trải phẳng tờ giấy</div>
            <div class="pending-step active">3. Đang căn mốc và chấm OMR</div>
          </div>
          <p class="scan-result-subtitle">${escapeHtml(text)}</p>
        </article>
      </div>
    `;
    resultContent.innerHTML = "";
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function showCaptureError(previewSrc, message) {
    resultPanel.hidden = false;
    resultTitle.textContent = "Chụp xong nhưng chấm chưa thành công";
    resultSubtitle.textContent = "Ảnh vừa chụp nằm ngay bên dưới. Bạn có thể quét tiếp hoặc chỉnh lại cách đặt phiếu.";
    resultSummary.innerHTML = `
      <div class="capture-review">
        <article class="surface capture-card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Ảnh vừa chụp</p>
              <h2>Frame camera cuối cùng</h2>
            </div>
          </div>
          <div class="capture-thumb-frame">
            <img class="capture-thumb" src="${previewSrc}" alt="Ảnh camera vừa chụp">
          </div>
        </article>
        <article class="surface capture-card scan-pending scan-error">
          <div class="section-head">
            <div>
              <p class="eyebrow">Lỗi xử lý</p>
              <h2>Server chưa chấm được frame này</h2>
            </div>
          </div>
          <p class="scan-result-subtitle">${escapeHtml(message)}</p>
        </article>
      </div>
    `;
    resultContent.innerHTML = "";
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function runPreview() {
    if (!state.stream || state.previewBusy || state.gradeBusy || state.autoPaused) {
      schedulePreview(420);
      return;
    }
    if (!video.videoWidth || !video.videoHeight) {
      schedulePreview(320);
      return;
    }

    state.previewBusy = true;
    try {
      const maxSide = 720;
      const scale = Math.min(maxSide / video.videoWidth, maxSide / video.videoHeight, 1);
      previewCanvas.width = Math.round(video.videoWidth * scale);
      previewCanvas.height = Math.round(video.videoHeight * scale);
      previewCanvas.getContext("2d").drawImage(video, 0, 0, previewCanvas.width, previewCanvas.height);
      const blob = await canvasToBlob(previewCanvas, "image/jpeg", 0.8);
      const formData = new FormData();
      formData.append("frame", blob, "preview.jpg");

      const response = await fetch(previewUrl, {
        method: "POST",
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Khong phan tich duoc khung hinh.");
      }

      drawGuide(payload);
      updateMetrics(payload);

      if (!payload.detected) {
        setStatus("Chưa bắt được 4 mép giấy", "Đưa cả tờ phiếu vào khung dọc, nền gọn hơn và để thấy rõ 4 cạnh.", "warning");
      } else if (!payload.ready) {
        const coverage = payload.metrics?.coverage || 0;
        const sharpness = payload.metrics?.sharpness || 0;
        const confidence = payload.metrics?.confidence || 0;
        let hint = "Đã thấy tờ phiếu nhưng cần giữ chắc tay hơn để hệ thống tự chụp.";
        if (coverage < 0.28) {
          hint = "Tờ phiếu đang hơi nhỏ trong khung. Đưa gần hơn hoặc căn để giấy chiếm nhiều diện tích hơn.";
        } else if (sharpness < 18) {
          hint = "Đã bắt được phiếu nhưng còn rung hoặc out nét. Giữ yên thêm một nhịp rồi chụp.";
        } else if (confidence < 0.55) {
          hint = "Contour bắt được còn yếu. Thử để nền đơn giản hơn và tránh bóng đổ ở mép giấy.";
        }
        setStatus("Đã thấy phiếu", hint, "neutral");
      } else {
        setStatus("Khung hình đạt", "4 góc đã rõ. Giữ yên thêm một nhịp ngắn, hệ thống sẽ tự chụp.", "success");
      }

      captureButton.disabled = !payload.detected;

      if (updateStability(payload)) {
        triggerGrade(true);
        return;
      }
    } catch (error) {
      drawGuide({ detected: false, corners: [] });
      setStatus("Preview lỗi", error.message || "Khong doc duoc frame camera.", "danger");
    } finally {
      state.previewBusy = false;
      schedulePreview(460);
    }
  }

  async function triggerGrade(autoCapture) {
    if (!state.stream || state.gradeBusy || !video.videoWidth || !video.videoHeight) {
      return;
    }

    state.gradeBusy = true;
    state.autoPaused = true;
    state.stableFrames = 0;
    flashCapture();
    state.lastCapturePreview = "";
    setStatus(
      autoCapture ? "Đang tự chụp và chấm" : "Đang chấm từ camera",
      "Ảnh vừa chụp sẽ hiện ngay bên dưới, sau đó server sẽ trải phẳng, căn chỉnh và chấm OMR.",
      "success",
    );

    try {
      const maxSide = 1800;
      const scale = Math.min(maxSide / video.videoWidth, maxSide / video.videoHeight, 1);
      fullCanvas.width = Math.round(video.videoWidth * scale);
      fullCanvas.height = Math.round(video.videoHeight * scale);
      fullCanvas.getContext("2d").drawImage(video, 0, 0, fullCanvas.width, fullCanvas.height);
      const capturePreview = fullCanvas.toDataURL("image/jpeg", 0.82);
      state.lastCapturePreview = capturePreview;
      showCapturedFrame(
        capturePreview,
        autoCapture ? "Đã tự chụp, đang chấm" : "Đã chụp, đang chấm",
        "Ảnh vừa chụp nằm ở đây. Chờ một nhịp để hệ thống trải phẳng và trả kết quả bên dưới.",
      );
      const blob = await canvasToBlob(fullCanvas, "image/jpeg", 0.92);
      const formData = currentAnswerFormData();
      formData.append("frame", blob, "camera-frame.jpg");

      const response = await fetch(gradeUrl, {
        method: "POST",
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Khong cham duoc phieu tu camera.");
      }

      renderResult(payload, capturePreview);
      resumeButton.hidden = false;
      setStatus("Đã chấm xong", "Kết quả đã hiện ngay phía dưới ảnh vừa chụp. Có thể quét tiếp bài khác.", "success");
    } catch (error) {
      state.autoPaused = false;
      resumeButton.hidden = true;
      if (state.lastCapturePreview) {
        showCaptureError(state.lastCapturePreview, error.message || "Khong cham duoc frame camera.");
      }
      setStatus("Chấm thất bại", error.message || "Khong cham duoc frame camera.", "danger");
    } finally {
      state.gradeBusy = false;
      schedulePreview(480);
    }
  }

  function formatStatus(item) {
    if (item.correct) {
      return "Đúng";
    }
    const raw = String(item.status || "");
    if (raw === "blank") {
      return "blank";
    }
    if (raw === "multiple") {
      return "multiple";
    }
    return raw || "-";
  }

  function renderRows(items, renderer) {
    return items.map(renderer).join("");
  }

  function renderResult(result, capturePreview) {
    resultTitle.textContent = "Đã quét xong";
    resultSubtitle.textContent = `Mã học sinh ${result.student_id} · Mã đề ${result.exam_code}`;

    resultSummary.innerHTML = `
      <div class="capture-review capture-review-complete">
        <article class="surface capture-card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Ảnh vừa chụp</p>
              <h2>Frame đã gửi lên server</h2>
            </div>
          </div>
          <div class="capture-thumb-frame">
            <img class="capture-thumb" src="${capturePreview}" alt="Ảnh camera vừa chụp">
          </div>
        </article>
        <section class="stats scan-stats">
          <article class="stat-card surface">
            <span>Tổng điểm quy đổi</span>
            <strong>${escapeHtml(result.totals.score_10)}</strong>
            <small>${escapeHtml(result.totals.overall.correct)}/${escapeHtml(result.totals.overall.total)} đơn vị đúng</small>
          </article>
          <article class="stat-card surface">
            <span>Phần I</span>
            <strong>${escapeHtml(result.totals.section1.correct)}/${escapeHtml(result.totals.section1.total)}</strong>
            <small>40 câu A/B/C/D</small>
          </article>
          <article class="stat-card surface">
            <span>Phần II</span>
            <strong>${escapeHtml(result.totals.section2.correct)}/${escapeHtml(result.totals.section2.total)}</strong>
            <small>32 ý đúng/sai</small>
          </article>
          <article class="stat-card surface">
            <span>Phần III</span>
            <strong>${escapeHtml(result.totals.section3.correct)}/${escapeHtml(result.totals.section3.total)}</strong>
            <small>6 câu trả lời ngắn</small>
          </article>
        </section>
      </div>
    `;

    resultContent.innerHTML = `
      <div class="result-layout scan-result-layout">
        <article class="surface overlay-card">
          <div class="section-head">
            <div>
              <p class="eyebrow">Ảnh kiểm tra</p>
              <h2>Overlay vùng đọc</h2>
            </div>
          </div>
          <div class="overlay-frame">
            <img class="overlay" src="data:image/png;base64,${result.overlay_base64}" alt="Ảnh overlay kết quả chấm realtime">
          </div>
          <p class="caption">Ngưỡng tô hiện tại: ${escapeHtml(result.calibration.threshold)} · Biên phân biệt: ${escapeHtml(result.calibration.margin)}.</p>
        </article>

        <div class="detail-stack">
          <section class="surface table-card">
            <div class="section-head">
              <div>
                <p class="eyebrow">Chi tiết Realtime</p>
                <h2>Phần I</h2>
              </div>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Câu</th>
                    <th>Đáp án</th>
                    <th>Bài làm</th>
                    <th>Trạng thái</th>
                  </tr>
                </thead>
                <tbody>
                  ${renderRows(result.section1, (item) => `
                    <tr class="${item.correct ? "ok" : "bad"}">
                      <td>${escapeHtml(item.question)}</td>
                      <td>${escapeHtml(item.expected)}</td>
                      <td>${escapeHtml(item.selected)}</td>
                      <td>${escapeHtml(formatStatus(item))}</td>
                    </tr>
                  `)}
                </tbody>
              </table>
            </div>
          </section>

          <section class="surface table-card">
            <div class="section-head">
              <div>
                <p class="eyebrow">Chi tiết Realtime</p>
                <h2>Phần II</h2>
              </div>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Câu</th>
                    <th>Ý</th>
                    <th>Đáp án</th>
                    <th>Bài làm</th>
                    <th>Trạng thái</th>
                  </tr>
                </thead>
                <tbody>
                  ${renderRows(result.section2, (item) => `
                    <tr class="${item.correct ? "ok" : "bad"}">
                      <td>${escapeHtml(item.question)}</td>
                      <td>${escapeHtml(item.statement)}</td>
                      <td>${escapeHtml(item.expected)}</td>
                      <td>${escapeHtml(item.selected)}</td>
                      <td>${escapeHtml(formatStatus(item))}</td>
                    </tr>
                  `)}
                </tbody>
              </table>
            </div>
          </section>

          <section class="surface table-card">
            <div class="section-head">
              <div>
                <p class="eyebrow">Chi tiết Realtime</p>
                <h2>Phần III</h2>
              </div>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Câu</th>
                    <th>Đáp án</th>
                    <th>Bài làm</th>
                    <th>Trạng thái</th>
                  </tr>
                </thead>
                <tbody>
                  ${renderRows(result.section3, (item) => `
                    <tr class="${item.correct ? "ok" : "bad"}">
                      <td>${escapeHtml(item.question)}</td>
                      <td>${escapeHtml(item.expected)}</td>
                      <td>${escapeHtml(item.selected)}</td>
                      <td>${escapeHtml(formatStatus(item))}</td>
                    </tr>
                  `)}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    `;
  }

  async function startCamera() {
    if (state.started) {
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus("Trình duyệt không hỗ trợ", "Thiết bị này không mở được camera bằng trình duyệt hiện tại.", "danger");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1080 },
          height: { ideal: 1920 },
          aspectRatio: { ideal: 0.75 },
        },
      });
      state.stream = stream;
      video.srcObject = stream;
      await video.play();
      state.started = true;
      placeholder.hidden = true;
      captureButton.disabled = false;
      startButton.disabled = true;
      setStatus("Camera đã mở", "Đưa tờ phiếu dọc vào giữa khung. Khi bắt được 4 mép giấy rõ, hệ thống sẽ tự chụp.", "neutral");
      drawGuide({ detected: false, corners: [] });
      schedulePreview(120);
    } catch (error) {
      setStatus("Không mở được camera", error.message || "Trình duyệt đã từ chối quyền truy cập camera.", "danger");
    }
  }

  function resumeScan() {
    state.autoPaused = false;
    state.stableFrames = 0;
    state.lastCorners = null;
    resumeButton.hidden = true;
    setStatus("Đang quét lại", "Đưa phiếu mới vào khung, hệ thống sẽ tiếp tục auto-capture.", "neutral");
    schedulePreview(120);
  }

  function stopCamera() {
    window.clearTimeout(state.previewTimer);
    if (state.stream) {
      state.stream.getTracks().forEach((track) => track.stop());
    }
  }

  startButton.addEventListener("click", startCamera);
  captureButton.addEventListener("click", () => triggerGrade(false));
  resumeButton.addEventListener("click", resumeScan);
  window.addEventListener("resize", () => drawGuide({ detected: false, corners: state.lastCorners || [] }));
  window.addEventListener("beforeunload", stopCamera);
  resetMetrics();
})();
