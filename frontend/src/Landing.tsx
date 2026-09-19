import { Logo } from './Logo'
import { ThemeToggle } from './theme/ThemeToggle'

// The API's own docs, on whatever origin the dashboard is built for.
const API_DOCS = `${(import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000').replace(/\/+$/, '')}/docs`
const REPO = 'https://github.com/matteodr99/metheon'

/**
 * The front door: what Metheon is, for someone arriving from a portfolio,
 * with the dashboard one click away. Every figure on it is real and dated
 * where it can drift; the counts that would drift are left out.
 */
export function Landing() {
  return (
    <div className="landing">
      <header className="landing-nav">
        <a href="/" className="brand" aria-label="Metheon home">
          <Logo size={26} />
          <span className="brand-name">Metheon</span>
        </a>
        <nav className="landing-links" aria-label="Sections">
          <a href="#how">How it works</a>
          <a href="#sources">Sources</a>
          <a href="#compare">Compare</a>
          <a href={REPO}>GitHub</a>
        </nav>
        <ThemeToggle />
        <a href="/app/" className="cta">
          Open the dashboard
        </a>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <p className="section-label">Open source · MIT · free to run</p>
          <h1 className="display">
            Public natural-event data, <em>agency by agency.</em>
          </h1>
          <p className="lede">
            Metheon ingests earthquake catalogues and disaster alerts from four public agencies
            into one schema, so the same filters, map and comparison work on all of them — and
            Gemini can say what the data shows.
          </p>
          <div className="hero-actions">
            <a href="/app/" className="cta">
              Open the dashboard
            </a>
            <a href={REPO} className="cta-secondary">
              Read the code
            </a>
          </div>
          <dl className="facts">
            <div>
              <dd>4</dd>
              <dt>agencies</dt>
            </div>
            <div>
              <dd>13</dd>
              <dt>kinds of event in the vocabulary</dt>
            </div>
            <div>
              <dd>6 h</dd>
              <dt>between refreshes</dt>
            </div>
            <div>
              <dd>€0</dd>
              <dt>a month to run</dt>
            </div>
          </dl>
        </div>
        <figure className="hero-card">
          <figcaption className="section-label">Compare · GDACS wildfires with NASA EONET</figcaption>
          <p className="hero-card-caption">
            45 of 222 events also reported by EONET · positions 4 km apart on average · areas
            differ by 2,752.7 ha on average
          </p>
          <table className="pairs">
            <tbody>
              <tr>
                <td>
                  <span>Forest fires in Namibia</span>
                  <span className="muted">Wildfire in Namibia 1031888</span>
                </td>
                <td className="numeric">
                  <span>61,629 ha</span>
                  <span className="muted">10,146 ha</span>
                </td>
                <td className="numeric delta">−51,483</td>
              </tr>
              <tr>
                <td>
                  <span>Forest fires in Angola</span>
                  <span className="muted">Wildfire in Angola 1031901</span>
                </td>
                <td className="numeric">
                  <span>22,193 ha</span>
                  <span className="muted">7,070 ha</span>
                </td>
                <td className="numeric delta">−15,123</td>
              </tr>
              <tr>
                <td>
                  <span>Forest fires in Botswana</span>
                  <span className="muted">Wildfire in Botswana 1031898</span>
                </td>
                <td className="numeric">
                  <span>15,357 ha</span>
                  <span className="muted">11,123 ha</span>
                </td>
                <td className="numeric delta">−4,234</td>
              </tr>
            </tbody>
          </table>
          <p className="muted small">
            Real pairs from the dashboard, 15 September 2026. Different networks explain most
            differences; neither agency is wrong.
          </p>
        </figure>
      </section>

      <section id="how" className="band">
        <div className="band-head">
          <p className="section-label">How it works</p>
          <h2 className="display">One pipeline, whatever the agency calls its feed.</h2>
        </div>
        <ol className="steps">
          <li>
            <span className="step-number">01</span>
            <strong>Ingest</strong>
            <span>GeoJSON, FDSN queries, JSON, RSS — each source module maps only its own quirks.</span>
          </li>
          <li>
            <span className="step-number">02</span>
            <strong>Validate</strong>
            <span>Ids, geometry, coordinate ranges, duplicates. Every run records what it refused, and why.</span>
          </li>
          <li>
            <span className="step-number">03</span>
            <strong>Normalize</strong>
            <span>One unit per kind — hectares, knots, a seismic scale — whichever agency reported it.</span>
          </li>
          <li>
            <span className="step-number">04</span>
            <strong>Store</strong>
            <span>PostgreSQL, one events table, idempotent upserts. Re-running refreshes; it never duplicates.</span>
          </li>
          <li>
            <span className="step-number">05</span>
            <strong>Query</strong>
            <span>A FastAPI with filters, aggregates, map points and cross-agency pairing, documented at /docs — and the same data as a GraphQL schema.</span>
          </li>
          <li>
            <span className="step-number">06</span>
            <strong>Ask</strong>
            <span>Gemini sees the aggregate, never the rows, and answers in a fixed JSON shape — including how two agencies compare.</span>
          </li>
        </ol>
      </section>

      <section id="sources" className="band split">
        <div className="band-head">
          <p className="section-label">Sources</p>
          <h2 className="display">Four agencies, one table.</h2>
          <p className="muted">
            A dataset holds events of one kind. The kind names the measure and decides the
            columns; the agencies decide nothing about the schema.
          </p>
        </div>
        <ul className="agencies">
          <li>
            <span className="dot kind-earthquake" />
            <strong>USGS</strong>
            <span>Earthquakes worldwide above M4.5, and everything in the United States.</span>
          </li>
          <li>
            <span className="dot kind-earthquake" />
            <strong>INGV</strong>
            <span>Italy in fine detail, down to magnitude 1, plus the strong events elsewhere.</span>
          </li>
          <li>
            <span className="dot kind-wildfire" />
            <strong>NASA EONET</strong>
            <span>Wildfires, storms, floods, sea ice — thirteen kinds, curated from satellite and partner reports.</span>
          </li>
          <li className="wide">
            <span className="dot kind-storm" />
            <strong>GDACS</strong>
            <span>
              The UN and EU alert system: earthquakes, cyclones, floods, volcanoes, wildfires and
              droughts, each graded Green, Orange or Red by expected impact.
            </span>
          </li>
        </ul>
      </section>

      <section id="compare" className="band split">
        <div className="band-head">
          <p className="section-label">Compare</p>
          <h2 className="display">The same earthquake, three magnitudes.</h2>
          <p>
            Agencies observe the same event with different networks and methods. Metheon pairs
            their reports — nearest in time, within a radius — and puts the differences side by
            side: epicentres kilometres apart, a fire three times larger in one catalogue than
            the other, a magnitude that agrees to the decimal because one agency takes its
            seismic data from the other.
          </p>
        </div>
        <figure className="hero-card">
          <figcaption className="section-label">Vanuatu, 10 September 2026</figcaption>
          <div className="readings">
            <div>
              <span className="muted">USGS</span>
              <span className="reading">
                5.6 <small>mww</small>
              </span>
              <span className="muted">depth 10 km</span>
            </div>
            <div>
              <span className="muted">INGV</span>
              <span className="reading">
                5.9 <small>mwp</small>
              </span>
              <span className="muted">depth 68 km</span>
            </div>
            <div>
              <span className="muted">GDACS</span>
              <span className="reading">
                5.6 <small>m</small>
              </span>
              <span className="muted">alert green</span>
            </div>
          </div>
          <p className="muted small">Epicentres 33 km apart, origin times 7 s apart. Real values from the dashboard.</p>
        </figure>
      </section>

      <section className="band split">
        <div className="band-head">
          <p className="section-label">Built to run for nothing</p>
          <h2 className="display">Free tiers, honestly used.</h2>
          <p className="muted">
            No worker in production, so ingestion runs inline and a scheduled job stands in for
            the queue. Every limit is a design decision written down in the repository.
          </p>
        </div>
        <dl className="hosting">
          <div>
            <dt>API</dt>
            <dd>Render, one free web service</dd>
          </div>
          <div>
            <dt>Database</dt>
            <dd>Neon PostgreSQL, 0.5 GB</dd>
          </div>
          <div>
            <dt>Dashboard</dt>
            <dd>Cloudflare Pages</dd>
          </div>
          <div>
            <dt>Refresh</dt>
            <dd>GitHub Actions, every six hours</dd>
          </div>
          <div>
            <dt>AI</dt>
            <dd>Gemini, free tier</dd>
          </div>
          <div>
            <dt>Tests</dt>
            <dd>Backend, frontend and image, on every push</dd>
          </div>
        </dl>
      </section>

      <footer className="landing-foot">
        <span className="brand">
          <Logo size={20} />
          <span>Metheon · a portfolio project by Matteo De Ronzis · MIT</span>
        </span>
        <nav className="landing-links" aria-label="Elsewhere">
          <a href="/app/">Dashboard</a>
          <a href={API_DOCS}>API docs</a>
          <a href={REPO}>GitHub</a>
        </nav>
      </footer>
    </div>
  )
}
