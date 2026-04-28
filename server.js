import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import nodemailer from "nodemailer";
import Database from "better-sqlite3";
import bcrypt from "bcryptjs";
import { v4 as uuidv4 } from "uuid";

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());

const API_KEY = process.env.GROQ_API_KEY;
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";

// ── DATABASE SETUP ──
const db = new Database("medimind.db");

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    joined_at INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS medicines (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    dose TEXT,
    time TEXT NOT NULL,
    specific_time TEXT,
    taken INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
  );
`);

console.log("✅ SQLite database ready");

// ── EMAIL TRANSPORTER ──
const transporter = nodemailer.createTransport({
  service: "gmail",
  auth: {
    user: process.env.EMAIL_USER,
    pass: process.env.EMAIL_PASS
  }
});

// ── GROQ HELPER ──
async function askGroq(prompt, maxTokens = 800) {
  const response = await fetch(GROQ_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${API_KEY}`
    },
    body: JSON.stringify({
      model: "llama-3.3-70b-versatile",
      messages: [{ role: "user", content: prompt }],
      max_tokens: maxTokens
    })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(data));
  return data?.choices?.[0]?.message?.content || null;
}

// ══════════════════════════════════════
// AUTH ROUTES
// ══════════════════════════════════════

// ✅ REGISTER
app.post("/register", async (req, res) => {
  const { name, email, password } = req.body;
  if (!name || !email || !password) return res.status(400).json({ error: "All fields are required." });
  if (password.length < 6) return res.status(400).json({ error: "Password must be at least 6 characters." });

  const existing = db.prepare("SELECT id FROM users WHERE email = ?").get(email);
  if (existing) return res.status(400).json({ error: "Email already registered." });

  const hashed = await bcrypt.hash(password, 10);
  const id = uuidv4();
  const joinedAt = Date.now();

  db.prepare("INSERT INTO users (id, name, email, password, joined_at) VALUES (?, ?, ?, ?, ?)")
    .run(id, name, email, hashed, joinedAt);

  const user = { id, name, email, joinedAt };
  res.json({ user });
});

// ✅ LOGIN
app.post("/login", async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) return res.status(400).json({ error: "All fields are required." });

  const user = db.prepare("SELECT * FROM users WHERE email = ?").get(email);
  if (!user) return res.status(401).json({ error: "Invalid email or password." });

  const match = await bcrypt.compare(password, user.password);
  if (!match) return res.status(401).json({ error: "Invalid email or password." });

  res.json({ user: { id: user.id, name: user.name, email: user.email, joinedAt: user.joined_at } });
});

// ✅ UPDATE PROFILE
app.put("/user/:id", async (req, res) => {
  const { name, email, password } = req.body;
  const { id } = req.params;

  if (!name || !email) return res.status(400).json({ error: "Name and email are required." });

  const taken = db.prepare("SELECT id FROM users WHERE email = ? AND id != ?").get(email, id);
  if (taken) return res.status(400).json({ error: "Email already used by another account." });

  if (password) {
    if (password.length < 6) return res.status(400).json({ error: "Password must be at least 6 characters." });
    const hashed = await bcrypt.hash(password, 10);
    db.prepare("UPDATE users SET name = ?, email = ?, password = ? WHERE id = ?").run(name, email, hashed, id);
  } else {
    db.prepare("UPDATE users SET name = ?, email = ? WHERE id = ?").run(name, email, id);
  }

  const user = db.prepare("SELECT * FROM users WHERE id = ?").get(id);
  res.json({ user: { id: user.id, name: user.name, email: user.email, joinedAt: user.joined_at } });
});

// ══════════════════════════════════════
// MEDICINE ROUTES
// ══════════════════════════════════════

// ✅ GET MEDICINES
app.get("/medicines/:userId", (req, res) => {
  const medicines = db.prepare("SELECT * FROM medicines WHERE user_id = ? ORDER BY created_at ASC").all(req.params.userId);
  res.json({ medicines: medicines.map(formatMed) });
});

// ✅ ADD MEDICINE
app.post("/medicines", (req, res) => {
  const { userId, name, dose, time, specificTime } = req.body;
  if (!userId || !name || !time) return res.status(400).json({ error: "userId, name and time are required." });

  const id = uuidv4();
  db.prepare("INSERT INTO medicines (id, user_id, name, dose, time, specific_time, taken, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)")
    .run(id, userId, name, dose || "", time, specificTime || "", Date.now());

  const med = db.prepare("SELECT * FROM medicines WHERE id = ?").get(id);
  res.json({ medicine: formatMed(med) });
});

// ✅ TOGGLE TAKEN
app.patch("/medicines/:id/toggle", (req, res) => {
  const med = db.prepare("SELECT * FROM medicines WHERE id = ?").get(req.params.id);
  if (!med) return res.status(404).json({ error: "Medicine not found." });

  const newTaken = med.taken ? 0 : 1;
  db.prepare("UPDATE medicines SET taken = ? WHERE id = ?").run(newTaken, req.params.id);
  res.json({ medicine: formatMed({ ...med, taken: newTaken }) });
});

// ✅ DELETE MEDICINE
app.delete("/medicines/:id", (req, res) => {
  db.prepare("DELETE FROM medicines WHERE id = ?").run(req.params.id);
  res.json({ success: true });
});

// ✅ RESET TAKEN (daily reset)
app.post("/medicines/reset/:userId", (req, res) => {
  db.prepare("UPDATE medicines SET taken = 0 WHERE user_id = ?").run(req.params.userId);
  res.json({ success: true });
});

function formatMed(m) {
  return {
    id: m.id,
    userId: m.user_id,
    name: m.name,
    dose: m.dose,
    time: m.time,
    specificTime: m.specific_time,
    taken: m.taken === 1,
    createdAt: m.created_at
  };
}

// ══════════════════════════════════════
// AI ROUTES
// ══════════════════════════════════════

// ✅ CHAT ROUTE
app.post("/chat", async (req, res) => {
  const { message } = req.body;
  try {
    const text = await askGroq(message);
    if (!text) return res.json({ content: [{ text: "⚠️ AI failed. Check API key." }] });
    res.json({ content: [{ text }] });
  } catch (err) {
    console.error("CHAT ERROR:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ✅ SYMPTOMS ROUTE
app.post("/symptoms", async (req, res) => {
  const { symptoms } = req.body;
  const prompt = `User has these symptoms: ${symptoms.join(", ")}.
Give:
1. Possible causes
2. OTC medicines
3. Home remedies
4. What to avoid
5. When to see a doctor`;
  try {
    const text = await askGroq(prompt);
    if (!text) return res.json({ content: [{ text: "⚠️ AI failed." }] });
    res.json({ content: [{ text }] });
  } catch (err) {
    console.error("SYMPTOMS ERROR:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ✅ HEALTH ANALYSIS ROUTE
app.post("/health-analysis", async (req, res) => {
  const { medicines, takenCount, totalCount, userName } = req.body;

  const medList = medicines.map(m =>
    `- ${m.name} (${m.dose || "no dose"}) at ${m.time}${m.specificTime ? " " + m.specificTime : ""} — ${m.taken ? "TAKEN" : "PENDING"}`
  ).join("\n");

  const prompt = `You are a health AI assistant. Analyze this patient's medication data and provide a brief health analysis.

Patient: ${userName}
Today's adherence: ${takenCount} out of ${totalCount} medicines taken.

Medicines:
${medList || "No medicines scheduled."}

Provide:
1. Adherence Score (e.g. "80% — Good")
2. Quick Health Insight based on the medicines (e.g. what conditions they might be managing)
3. Today's Recommendation (1-2 sentences)
4. A motivational tip

Keep it concise, friendly, and under 200 words. Do not diagnose.`;

  try {
    const text = await askGroq(prompt, 400);
    if (!text) return res.json({ content: [{ text: "⚠️ Analysis unavailable." }] });
    res.json({ content: [{ text }] });
  } catch (err) {
    console.error("HEALTH ANALYSIS ERROR:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// ✅ EMAIL REMINDER ROUTE
app.post("/send-reminder", async (req, res) => {
  const { email, userName, medicines } = req.body;

  if (!email || !medicines || medicines.length === 0) {
    return res.status(400).json({ error: "Email and medicines are required." });
  }

  const pending = medicines.filter(m => !m.taken);
  if (pending.length === 0) {
    return res.json({ message: "No pending medicines to remind about." });
  }

  const medRows = pending.map(m =>
    `<tr>
      <td style="padding:10px 14px; border-bottom:1px solid #2a3441; font-weight:600; color:#e8edf3">${m.name}</td>
      <td style="padding:10px 14px; border-bottom:1px solid #2a3441; color:#7a8899">${m.dose || "—"}</td>
      <td style="padding:10px 14px; border-bottom:1px solid #2a3441; color:#ffaa00">${capitalize(m.time)}${m.specificTime ? " · " + m.specificTime : ""}</td>
    </tr>`
  ).join("");

  const html = `
  <div style="font-family:'Segoe UI',sans-serif; background:#0d1117; padding:32px; max-width:560px; margin:0 auto; border-radius:16px;">
    <div style="text-align:center; margin-bottom:28px;">
      <div style="display:inline-block; background:#00e5a0; border-radius:12px; padding:10px 18px; font-size:22px; font-weight:800; color:#000; letter-spacing:1px;">💊 MediMind</div>
    </div>
    <h2 style="color:#e8edf3; font-size:20px; margin-bottom:6px;">Hi ${userName}! 👋</h2>
    <p style="color:#7a8899; font-size:15px; margin-bottom:24px;">You have <strong style="color:#ffaa00">${pending.length} pending medicine(s)</strong> to take today. Don't forget!</p>
    <table style="width:100%; border-collapse:collapse; background:#161b22; border-radius:12px; overflow:hidden; border:1px solid #2a3441;">
      <thead>
        <tr style="background:#1e2631;">
          <th style="padding:10px 14px; text-align:left; color:#7a8899; font-size:12px; text-transform:uppercase; letter-spacing:0.08em;">Medicine</th>
          <th style="padding:10px 14px; text-align:left; color:#7a8899; font-size:12px; text-transform:uppercase; letter-spacing:0.08em;">Dosage</th>
          <th style="padding:10px 14px; text-align:left; color:#7a8899; font-size:12px; text-transform:uppercase; letter-spacing:0.08em;">Time</th>
        </tr>
      </thead>
      <tbody>${medRows}</tbody>
    </table>
    <p style="color:#7a8899; font-size:13px; margin-top:24px; text-align:center;">Stay consistent — your health depends on it! 💪</p>
    <p style="color:#2a3441; font-size:11px; text-align:center; margin-top:16px;">Sent by MediMind · Do not reply to this email</p>
  </div>`;

  try {
    await transporter.sendMail({
      from: `"MediMind 💊" <${process.env.EMAIL_USER}>`,
      to: email,
      subject: `💊 Reminder: ${pending.length} medicine(s) pending today — MediMind`,
      html
    });
    console.log(`Email sent to ${email}`);
    res.json({ message: "Reminder email sent successfully!" });
  } catch (err) {
    console.error("EMAIL ERROR:", err.message);
    res.status(500).json({ error: "Failed to send email: " + err.message });
  }
});

app.get("/test", (req, res) => {
  res.send("Backend is working ✅");
});

// 🚀 START SERVER
app.listen(3000, () => {
  console.log("Server running on http://localhost:3000");
});

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
app.get("/", (req, res) => {
  res.send("MediMind AI backend is running 🚀");
});
