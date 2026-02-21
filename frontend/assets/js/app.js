const API_URL = "http://localhost:8000";

// Force HTTP origin to fix file:/// localStorage isolation bugs in Chrome
if (window.location.protocol === "file:") {
  const page = window.location.pathname.split("/").pop() || "index.html";
  window.location.href = `${API_URL}/${page}`;
}

// ==========================================
// USER MANAGEMENT
// ==========================================

function getUserId() {
  return localStorage.getItem("mentra_user_id");
}

function requireUser() {
  const path = window.location.pathname.toLowerCase();

  // Do not redirect if we are already on users or index page
  if (path.includes("users.html") || path.includes("index.html") || path.endsWith("/")) {
    return;
  }

  // Otherwise, redirect if no active user
  if (!getUserId()) {
    window.location.href = "users.html";
  }
}

// Ensure the user is logged in
requireUser();

async function loadUsersList() {
  const listDiv = document.getElementById("users-list");
  if (!listDiv) return;

  try {
    const res = await fetch(`${API_URL}/users/`);
    const users = await res.json();

    listDiv.innerHTML = "";
    if (users.length === 0) {
      listDiv.innerHTML = '<p class="text-muted text-center" style="font-size: 0.9rem;">No profiles found. Create one below.</p>';
      return;
    }

    users.forEach(u => {
      const btn = document.createElement("button");
      btn.className = "secondary-btn mb-2";
      btn.style.width = "100%";
      btn.style.textAlign = "left";
      btn.innerHTML = `👤 ${u.username}`;
      btn.onclick = () => {
        localStorage.setItem("mentra_user_id", u.id);
        localStorage.setItem("mentra_username", u.username);
        window.location.href = "dashboard.html";
      };
      listDiv.appendChild(btn);
    });
  } catch (e) {
    listDiv.innerHTML = '<p class="text-danger">Failed to load profiles.</p>';
  }
}

async function createUser() {
  const input = document.getElementById("new-username");
  const username = input.value.trim();
  if (!username) return alert("Please enter a name.");

  try {
    const res = await fetch(`${API_URL}/users/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username })
    });

    if (res.ok) {
      const user = await res.json();
      localStorage.setItem("mentra_user_id", user.id);
      localStorage.setItem("mentra_username", user.username);
      window.location.href = "dashboard.html";
    } else {
      alert("Failed to create user. Ensure username is unique.");
    }
  } catch (e) {
    alert("API Error creating user.");
  }
}

// Update UI to show active user if present
document.addEventListener("DOMContentLoaded", () => {
  const uName = localStorage.getItem("mentra_username");
  const navLinks = document.querySelector(".nav-links");
  if (uName && navLinks) {
    const profileSpan = document.createElement("a");
    profileSpan.href = "users.html";
    profileSpan.style.opacity = "0.7";
    profileSpan.innerHTML = `👤 ${uName}`;
    navLinks.prepend(profileSpan);
  }
});


// ==========================================
// CHAT LOGIC
// ==========================================
async function sendMessage() {
  const input = document.getElementById("user-input");
  const chatBox = document.getElementById("chat-box");
  const userId = getUserId();
  if (!userId) return alert("Please select a profile first.");

  const userText = input.value.trim();
  if (!userText) return;

  const userMsgDiv = document.createElement("div");
  userMsgDiv.className = "chat-message user";
  userMsgDiv.textContent = userText;
  chatBox.appendChild(userMsgDiv);

  input.value = "";
  chatBox.scrollTop = chatBox.scrollHeight;

  const loadingDiv = document.createElement("div");
  loadingDiv.className = "chat-message ai";
  loadingDiv.innerHTML = '<span style="opacity:0.5;">Thinking...</span>';
  chatBox.appendChild(loadingDiv);
  chatBox.scrollTop = chatBox.scrollHeight;

  try {
    const res = await fetch(`${API_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: parseInt(userId), message: userText })
    });

    if (!res.ok) throw new Error("Network error");
    const data = await res.json();
    loadingDiv.innerHTML = data.reply.replace(/\n/g, '<br>');
  } catch (error) {
    loadingDiv.innerHTML = '<span style="color:#ef4444;">Error connecting to processing unit.</span>';
  }
  chatBox.scrollTop = chatBox.scrollHeight;
}

// ==========================================
// JOURNAL LOGIC
// ==========================================
const sliders = ["mood", "anxiety", "stress", "energy", "sleep-quality", "social"];
sliders.forEach(id => {
  const slider = document.getElementById(id);
  if (slider) {
    const valueDisplay = document.getElementById(id + "-value");
    slider.addEventListener("input", () => {
      valueDisplay.textContent = slider.value;
    });
  }
});

async function saveJournal() {
  const userId = getUserId();
  if (!userId) {
    alert("Please select a user profile first!");
    return window.location.href = "users.html";
  }

  const btn = document.querySelector(".primary-btn");
  const originalText = btn.textContent;
  btn.textContent = "Saving...";
  btn.style.opacity = "0.7";
  btn.disabled = true;

  const data = {
    user_id: parseInt(userId),
    journal_text: document.getElementById("journal-text").value,
    mood: parseInt(document.getElementById("mood").value),
    anxiety: parseInt(document.getElementById("anxiety").value),
    stress: parseInt(document.getElementById("stress").value),
    energy: parseInt(document.getElementById("energy").value),
    productivity: parseInt(document.getElementById("productivity").value || 5),
    sleep_hours: parseFloat(document.getElementById("sleep-hours").value),
    sleep_quality: parseInt(document.getElementById("sleep-quality").value),
    social_connection: parseInt(document.getElementById("social").value)
  };

  try {
    const res = await fetch(`${API_URL}/journal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });

    if (res.ok) {
      btn.textContent = "Saved Successfully!";
      btn.style.background = "var(--success)";
      setTimeout(() => window.location.href = "dashboard.html", 1500);
    } else {
      throw new Error("Failed to save");
    }
  } catch (e) {
    alert("Error saving journal entry.");
    btn.textContent = originalText;
    btn.style.opacity = "1";
    btn.disabled = false;
  }
}

// ==========================================
// JOURNAL HISTORY LOGIC
// ==========================================
async function loadJournalHistory() {
  const userId = getUserId();
  if (!userId) return;

  const historyDiv = document.getElementById("journal-history");
  if (!historyDiv) return;

  try {
    const res = await fetch(`${API_URL}/entries?user_id=${userId}`);
    if (!res.ok) throw new Error("Failed to fetch history");
    const entries = await res.json();

    historyDiv.innerHTML = "";

    if (entries.length === 0) {
      historyDiv.innerHTML = '<p class="text-muted text-center" style="font-size: 0.9rem;">No past entries found. Start journaling above!</p>';
      return;
    }

    entries.forEach(entry => {
      const dt = new Date(entry.date);
      const dateStr = dt.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
      const timeStr = dt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

      const card = document.createElement("div");
      card.className = "card mb-3";
      card.style.padding = "1.5rem";
      card.style.background = "rgba(255, 255, 255, 0.02)";

      let html = `<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                    <h4 style="margin: 0; color: var(--primary); font-size: 1.1rem;">${dateStr}</h4>
                    <span class="text-muted" style="font-size: 0.85rem;">${timeStr}</span>
                  </div>`;

      if (entry.journal_text) {
        html += `<p style="margin-bottom: 1rem; line-height: 1.6; white-space: pre-wrap; color: var(--text-primary);">${entry.journal_text}</p>`;
      }

      html += `<div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                 <span class="metric-status" style="background: rgba(99, 102, 241, 0.1); color: #818cf8; padding: 0.3rem 0.6rem; border-radius: 4px; font-size: 0.8rem;">Mood: ${entry.mood}/10</span>
                 <span class="metric-status" style="background: rgba(245, 158, 11, 0.1); color: #fbbf24; padding: 0.3rem 0.6rem; border-radius: 4px; font-size: 0.8rem;">Anxiety: ${entry.anxiety}/10</span>
                 <span class="metric-status" style="background: rgba(239, 68, 68, 0.1); color: #f87171; padding: 0.3rem 0.6rem; border-radius: 4px; font-size: 0.8rem;">Stress: ${entry.stress}/10</span>
                <span class="metric-status" style="background: rgba(16, 185, 129, 0.1); color: #34d399; padding: 0.3rem 0.6rem; border-radius: 4px; font-size: 0.8rem;">Sleep: ${entry.sleep_hours}h</span>
               </div>`;

      card.innerHTML = html;
      historyDiv.appendChild(card);
    });
  } catch (e) {
    console.error("Error loading history:", e);
    historyDiv.innerHTML = '<p class="text-danger text-center">Failed to load past entries.</p>';
  }
}
// ==========================================
// DASHBOARD LOGIC
// ==========================================
async function initDashboard() {
  const userId = getUserId();
  if (!userId) return;

  try {
    const overviewRes = await fetch(`${API_URL}/dashboard/overview?user_id=${userId}`);
    if (overviewRes.ok) {
      const overview = await overviewRes.json();

      document.getElementById("avg-mood").textContent = overview.avg_mood_7d;
      document.getElementById("avg-anxiety").textContent = overview.avg_anxiety;
      document.getElementById("avg-stress").textContent = overview.avg_stress;
      document.getElementById("avg-sleep").textContent = overview.avg_sleep;
      document.getElementById("journal-streak").textContent = overview.journal_streak;

      document.getElementById("stability").textContent = overview.emotional_stability_index;

      const burnoutEl = document.getElementById("burnout");
      burnoutEl.textContent = overview.burnout_risk;
      burnoutEl.className = `metric-status status-${overview.burnout_risk.toLowerCase()}`;

      const isolationEl = document.getElementById("isolation");
      isolationEl.textContent = overview.isolation_risk;
      isolationEl.className = `metric-status status-${overview.isolation_risk.toLowerCase()}`;
    }

    const entriesRes = await fetch(`${API_URL}/entries/last7?user_id=${userId}`);
    if (entriesRes.ok) {
      const data = await entriesRes.json();
      // Force sort data by date ascending just in case
      data.sort((a, b) => new Date(a.date) - new Date(b.date));
      if (data && data.length > 0) {
        renderCharts(data);
      }
    }
  } catch (e) {
    console.error("Error loading dashboard data:", e);
  }
}

function renderCharts(data) {
  Chart.defaults.color = "#94A3B8";
  Chart.defaults.borderColor = "rgba(255, 255, 255, 0.05)";

  const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'top', labels: { usePointStyle: true, boxWidth: 6 } },
      tooltip: { backgroundColor: 'rgba(15, 23, 42, 0.9)', padding: 12, cornerRadius: 8 }
    },
    scales: {
      x: { grid: { display: false } },
      y: { grid: { color: 'rgba(255, 255, 255, 0.05)' } }
    }
  };

  // Convert raw ISO string to beautiful short date logic
  const dateLabels = data.map(d => {
    const dt = new Date(d.date);
    return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  });

  new Chart(document.getElementById("moodChart"), {
    type: 'line',
    data: {
      labels: dateLabels,
      datasets: [{
        label: "Mood Score",
        data: data.map(d => d.mood),
        borderColor: "#6366F1",
        backgroundColor: "rgba(99, 102, 241, 0.1)",
        borderWidth: 3,
        tension: 0.4,
        fill: true
      }]
    },
    options: { ...commonOptions, scales: { y: { min: 0, max: 10 } } }
  });

  new Chart(document.getElementById("stressSleepChart"), {
    type: 'line',
    data: {
      labels: dateLabels,
      datasets: [
        { label: "Stress", data: data.map(d => d.stress), borderColor: "#EF4444", tension: 0.4 },
        { label: "Sleep (hrs)", data: data.map(d => d.sleep_hours), borderColor: "#8B5CF6", tension: 0.4 }
      ]
    },
    options: commonOptions
  });

  new Chart(document.getElementById("anxietySocialChart"), {
    type: 'bar',
    data: {
      labels: dateLabels,
      datasets: [
        { label: "Anxiety", data: data.map(d => d.anxiety), backgroundColor: "#F59E0B" },
        { label: "Social", data: data.map(d => d.social_connection), backgroundColor: "#10B981" }
      ]
    },
    options: { ...commonOptions, scales: { y: { min: 0, max: 10 } } }
  });

  new Chart(document.getElementById("energyProductivityChart"), {
    type: 'line',
    data: {
      labels: dateLabels,
      datasets: [
        { label: "Energy", data: data.map(d => d.energy), borderColor: "#FBBF24", borderDash: [5, 5], tension: 0.4 },
        { label: "Productivity", data: data.map(d => d.productivity), borderColor: "#3B82F6", tension: 0.4 }
      ]
    },
    options: { ...commonOptions, scales: { y: { min: 0, max: 10 } } }
  });
}

if (window.location.pathname.includes("dashboard.html")) {
  initDashboard();
}

if (window.location.pathname.includes("journal.html")) {
  loadJournalHistory();
}