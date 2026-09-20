import { copy } from "@/lib/copy";
import LoginForm from "@/components/auth/login-form";
import RedirectIfAuthenticated from "@/components/auth/redirect-if-authenticated";

export default function LoginPage() {
  return (
    <RedirectIfAuthenticated>
      <main className="login-page">
        <section className="login-brand" aria-hidden="true">
          <div className="login-brand-mark">脑</div>
          <svg className="login-net" viewBox="0 0 320 460" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
            <g stroke="rgba(255,255,255,.26)" strokeWidth="1">
              <line x1="46" y1="70" x2="140" y2="170" />
              <line x1="140" y1="170" x2="80" y2="270" />
              <line x1="140" y1="170" x2="230" y2="130" />
              <line x1="230" y1="130" x2="286" y2="220" />
              <line x1="286" y1="220" x2="200" y2="330" />
              <line x1="80" y1="270" x2="170" y2="380" />
              <line x1="230" y1="130" x2="170" y2="380" />
              <line x1="46" y1="70" x2="230" y2="130" />
              <line x1="80" y1="270" x2="40" y2="360" />
            </g>
          </svg>
          <span className="login-node" style={{ left: "42px", top: "66px" }} />
          <span className="login-node" style={{ left: "136px", top: "166px" }} />
          <span className="login-node" style={{ left: "76px", top: "266px" }} />
          <span className="login-node" style={{ left: "226px", top: "126px" }} />
          <span className="login-node login-node--slow" style={{ left: "282px", top: "216px" }} />
          <span className="login-node" style={{ left: "196px", top: "326px" }} />
          <span className="login-node login-node--slow" style={{ left: "36px", top: "356px" }} />
          <span className="login-node" style={{ left: "166px", top: "376px" }} />
          <div className="login-brain">
            <span className="login-ai-chip">AI</span>
          </div>
          <div className="login-brand-copy">
            <div className="login-brand-kicker">AI SOLUTION WORKSPACE</div>
            <h1 className="login-brand-title">{copy.app.title}</h1>
            <p className="login-brand-desc">{copy.app.description}</p>
          </div>
          <div className="login-brand-foot">BRAIN SHELL · AGENT PLATFORM</div>
        </section>
        <section className="login-panel">
          <div className="login-card"><LoginForm /></div>
        </section>
      </main>
    </RedirectIfAuthenticated>
  );
}
