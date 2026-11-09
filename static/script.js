
const form = document.getElementById("recordForm");
const resultBox = document.getElementById("result");

async function loadDashboard() {
    try {
        const [statsResponse, recordsResponse] = await Promise.all([
            fetch("/api/stats"),
            fetch("/api/records")
        ]);

        if (!statsResponse.ok || !recordsResponse.ok) {
            throw new Error("Unable to load dashboard data");
        }

        const stats = await statsResponse.json();
        const records = await recordsResponse.json();

        document.getElementById("totalRecords").textContent =
            stats.total_records;

        document.getElementById("uniqueRecords").textContent =
            stats.unique_records;

        document.getElementById("duplicateRecords").textContent =
            stats.duplicates_prevented;

        document.getElementById("pendingReviews").textContent =
            stats.pending_reviews;

        document.getElementById("healthUnique").textContent =
            stats.unique_records;

        document.getElementById("databaseStatus").textContent =
            stats.database_status;

        const table = document.getElementById("recordsTable");

        if (records.length === 0) {
            table.innerHTML = `
                <tr>
                    <td colspan="5" class="empty">
                        No records available. Add your first record!
                    </td>
                </tr>`;
            return;
        }

        table.innerHTML = records.map(record => `
            <tr>
                <td>#${record.id}</td>
                <td><strong>${escapeHTML(record.title)}</strong></td>
                <td>${escapeHTML(record.category)}</td>
                <td>${escapeHTML(record.description)}</td>
                <td><span class="status-pill">✓ Verified</span></td>
            </tr>
        `).join("");

    } catch (error) {
        console.error(error);
        showResult("Unable to load dashboard. Check the server.", "error");
    }
}

// Prevent user data from being interpreted as HTML
function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
    })[char]);
}

function showResult(message, type) {
    resultBox.textContent = message;
    resultBox.className = "result " + type;
}

form.addEventListener("submit", async function(event) {
    event.preventDefault();

    const button = document.getElementById("submitBtn");

    const data = {
        title: document.getElementById("title").value.trim(),
        category: document.getElementById("category").value.trim(),
        description: document.getElementById("description").value.trim()
    };

    button.disabled = true;
    button.textContent = "Verifying data...";

    try {
        const response = await fetch("/api/records", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (result.status === "success") {
            showResult("✓ " + result.message, "success");
            form.reset();
            await loadDashboard();

        } else if (result.status === "duplicate") {
            showResult("⚠ " + result.message, "error");
            await loadDashboard();

        } else if (result.status === "review") {
            showResult("⚠ " + result.message, "review");
            await loadDashboard();

        } else {
            showResult("✕ " + result.message, "error");
        }

    } catch (error) {
        showResult("Server connection failed. Please try again.", "error");
    } finally {
        button.disabled = false;
        button.textContent = "Verify & Add Record →";
    }
});

loadDashboard();
