"use client";

import { useEffect, useState } from "react";

type HealthResponse = {
  api: string;
  database: string;
  cache: string;
};

export default function Home() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    fetch(`${apiUrl}/health`)
      .then((res) => res.json())
      .then(setHealth)
      .catch((err) => setError(String(err)));
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>FinSight</h1>
      <p>Phase 0 scaffold — this page confirms frontend → backend → Postgres/Valkey wiring.</p>
      {error && <p style={{ color: "red" }}>Error reaching backend: {error}</p>}
      {health && (
        <ul>
          <li>API: {health.api}</li>
          <li>Database: {health.database}</li>
          <li>Cache: {health.cache}</li>
        </ul>
      )}
      {!health && !error && <p>Checking backend health…</p>}
    </main>
  );
}
