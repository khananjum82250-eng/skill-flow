window.SkillFlowReport = {
  open(reportedUserId) {
    const modal = document.createElement("div");
    modal.className = "report-modal";
    modal.innerHTML = `
      <div class="report-box">
        <h3>Report User</h3>
        <label>Type
          <select id="reportReason">
            <option>Spam</option><option>Abuse</option><option>Fake</option><option>Other</option>
          </select>
        </label>
        <label>Description
          <textarea id="reportDescription" rows="4"></textarea>
        </label>
        <div class="report-actions">
          <button type="button" id="cancelReport">Cancel</button>
          <button type="button" id="submitReport">Submit</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    modal.querySelector("#cancelReport").addEventListener("click", () => modal.remove());
    modal.querySelector("#submitReport").addEventListener("click", () => {
      fetch("/api/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reported_user_id: reportedUserId,
          report_type: modal.querySelector("#reportReason").value,
          reason: modal.querySelector("#reportReason").value,
          description: modal.querySelector("#reportDescription").value
        })
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            SkillFlowUI.success("Report submitted");
            modal.remove();
            return;
          }
          SkillFlowUI.error(data.error || "Unable to submit report");
        })
        .catch(() => SkillFlowUI.error("Unable to submit report"));
    });
  }
};

document.querySelectorAll("[data-report-user]").forEach((button) => {
  button.addEventListener("click", () => window.SkillFlowReport.open(button.dataset.reportUser));
});
