import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, CircleAlert, ExternalLink, Play, RotateCcw, ShieldAlert, ShieldCheck, TriangleAlert, Undo2, X } from "lucide-react";
import AnimatedTabs from "@/components/ui/animated-tabs";
import { StatCard } from "@/components/ui/stat-card";
import { Status, StatusIndicator, StatusLabel } from "@/components/ui/status";
import { Button } from "@/components/ui/button";
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";

type Level = "green" | "yellow" | "red" | "na";
const VERDICT: Record<string, { label: string; short: string }> = {
  green: { label: "Rules passed", short: "Passed" },
  yellow: { label: "Check before approving", short: "Caution" },
  red: { label: "Rules advise against", short: "Advised against" },
};
const DOT: Record<string, string> = { green: "bg-green-600", yellow: "bg-amber-500", red: "bg-red-600", na: "bg-slate-300" };
const TINT: Record<string, string> = { green: "bg-green-600/[0.06]", yellow: "bg-amber-400/15", red: "bg-red-600/10", na: "" };

const Dot = ({ level, className }: { level: Level; className?: string }) => <span className={cn("inline-block size-2.5 shrink-0 rounded-full", DOT[level], className)} />;

function VerdictPill({ verdict, short }: { verdict: Level; short?: boolean }) {
  return (
    <Status variant={verdict as any}>
      <StatusIndicator pulse={verdict !== "green"} />
      <StatusLabel>{short ? VERDICT[verdict].short : VERDICT[verdict].label}</StatusLabel>
    </Status>
  );
}

async function post(url: string, body: any = {}) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}

export default function App() {
  const [data, setData] = useState<any>(null);
  const [tab, setTab] = useState("queue");
  const [filter, setFilter] = useState<string>("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [approving, setApproving] = useState<any>(null);
  const [rejecting, setRejecting] = useState<any>(null);
  const [undoAsk, setUndoAsk] = useState<any>(null);       // step 1 dialog
  const [undoConfirm, setUndoConfirm] = useState<any>(null); // step 2 dialog
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => setData(await (await fetch("/api/state")).json()), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(null), 6000); return () => clearTimeout(t); } }, [toast]);

  const list = useMemo(() => {
    if (!data) return [];
    const src = tab === "decided" ? data.decided : data.open;
    return filter === "all" || tab === "decided" ? src : src.filter((p: any) => p.verdict === filter);
  }, [data, tab, filter]);
  const current = list.find((p: any) => p.id === selected) ?? list[0];

  if (!data) return <div className="grid h-screen place-items-center text-muted-foreground">Loading the review queue…</div>;
  const count = (v: string) => data.open.filter((p: any) => p.verdict === v).length;

  const finish = async (res: any) => {
    setToast({ ok: !!res.ok, text: res.message || res.error });
    setApproving(null); setRejecting(null); setUndoAsk(null); setUndoConfirm(null); setBusy(false);
    await load();
  };
  const approve = async (p: any, body: any = {}) => { setBusy(true); finish(await post(`/api/proposals/${p.id}/approve`, body)); };
  const onApproveClick = (p: any) => (p.verdict === "green" ? approve(p) : setApproving(p));
  const run = async () => { setBusy(true); finish(await post("/api/run")); };
  const undoCall = async (p: any, step: string, body: any = {}) => { setBusy(true); finish(await post(`/api/proposals/${p.id}/${step}`, body)); };

  return (
    <div className="min-h-screen">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground"><ShieldCheck className="size-5" /></div>
            <div>
              <h1 className="font-semibold text-lg leading-tight tracking-tight">Bellhaven ownership sync</h1>
              <p className="text-muted-foreground text-sm">Website vs CRM · Reviewer: {data.reviewer} · Nothing is written until you approve it</p>
            </div>
          </div>
          <Button onClick={run} disabled={busy} variant="outline"><Play /> Run pipeline now</Button>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] space-y-5 px-6 py-6">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatCard title="To review" value={data.open.length} hint="All open proposals" active={tab === "queue" && filter === "all"} onClick={() => { setTab("queue"); setFilter("all"); }} />
          <StatCard title="Rules passed" tone="green" value={count("green")} hint="One click to approve" active={tab === "queue" && filter === "green"} onClick={() => { setTab("queue"); setFilter("green"); }} />
          <StatCard title="Caution" tone="yellow" value={count("yellow")} hint="Needs a confirmation" active={tab === "queue" && filter === "yellow"} onClick={() => { setTab("queue"); setFilter("yellow"); }} />
          <StatCard title="Advised against" tone="red" value={count("red")} hint="Needs an override and a reason" active={tab === "queue" && filter === "red"} onClick={() => { setTab("queue"); setFilter("red"); }} />
          <StatCard title="Decided" value={data.decided.length} hint={data.decided.some((p: any) => p.status === "undo_requested") ? "Undo waiting for step 2" : "Approved, rejected or reversed"} active={tab === "decided"} onClick={() => setTab("decided")} />
        </div>

        <AnimatedTabs activeTab={tab} onChange={setTab} tabs={[
          { id: "queue", label: "Review queue", count: data.open.length }, { id: "decided", label: "Decided", count: data.decided.length },
          { id: "matches", label: "Clean matches", count: data.matches.length }, { id: "rules", label: "Rules" }, { id: "activity", label: "Activity" }]} />

        <AnimatePresence mode="wait">
          <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }}>
            {(tab === "queue" || tab === "decided") && (
              list.length === 0 ? (
                <Empty text={tab === "queue" ? (data.open.length ? "Nothing in this filter." : "Queue is clear. Nothing is waiting for review. Run the pipeline to check again.") : "No decisions yet."} />
              ) : (
                <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
                  <aside className="space-y-1.5 lg:max-h-[calc(100vh-150px)] lg:overflow-y-auto lg:pr-1">
                    <AnimatePresence initial={false}>
                      {list.map((p: any) => (
                        <motion.button layout key={p.id} exit={{ opacity: 0, x: -20 }} onClick={() => setSelected(p.id)} type="button"
                          className={cn("flex w-full cursor-pointer items-start gap-3 rounded-lg border bg-card p-3 text-left transition-colors hover:border-primary/50",
                            current?.id === p.id && "border-primary bg-accent shadow-sm")}>
                          <Dot level={p.verdict} className="mt-1.5" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium text-sm">{p.title}</span>
                            <span className="text-muted-foreground text-xs">{p.kind_label}{p.status !== "pending" ? ` · ${p.status}` : ""}</span>
                          </span>
                        </motion.button>
                      ))}
                    </AnimatePresence>
                  </aside>
                  {current && <Detail key={current.id} p={current} busy={busy} onApprove={() => onApproveClick(current)} onReject={() => setRejecting(current)}
                    onUndo={() => setUndoAsk(current)} onUndoConfirm={() => setUndoConfirm(current)}
                    onUndoCancel={() => undoCall(current, "undo/cancel")} onReopen={() => undoCall(current, "reopen")} />}
                </div>
              )
            )}
            {tab === "matches" && <Matches matches={data.matches} />}
            {tab === "rules" && <Rules data={data} />}
            {tab === "activity" && <Activity data={data} />}
          </motion.div>
        </AnimatePresence>
      </main>

      <ApproveDialog p={approving} minReason={data.min_reason} busy={busy} onClose={() => setApproving(null)} onConfirm={approve} />
      <RejectDialog p={rejecting} busy={busy} onClose={() => setRejecting(null)}
        onConfirm={async (p: any, reason: string) => { setBusy(true); finish(await post(`/api/proposals/${p.id}/reject`, { reason })); }} />

      <UndoAskDialog p={undoAsk} minReason={data.min_undo_reason} busy={busy} onClose={() => setUndoAsk(null)}
        onConfirm={(p: any, reason: string) => undoCall(p, "undo/request", { reason })} />
      <UndoConfirmDialog p={undoConfirm} busy={busy} onClose={() => setUndoConfirm(null)}
        onConfirm={(p: any) => undoCall(p, "undo/confirm", { confirm_text: "UNDO", ack: true })} />

      <AnimatePresence>
        {toast && (
          <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 24 }} role="status"
            className={cn("fixed bottom-6 left-1/2 z-[60] flex max-w-[92vw] -translate-x-1/2 items-start gap-2 rounded-lg border px-4 py-3 text-sm shadow-xl",
              toast.ok ? "border-green-600/30 bg-green-50 text-green-900" : "border-red-600/30 bg-red-50 text-red-900")}>
            {toast.ok ? <Check className="mt-0.5 size-4" /> : <CircleAlert className="mt-0.5 size-4" />}<span>{toast.text}</span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

const Empty = ({ text }: { text: string }) => <div className="rounded-xl border border-dashed bg-card p-16 text-center text-muted-foreground">{text}</div>;
const H = ({ children }: any) => <h3 className="mb-2 font-mono font-medium text-[11px] text-muted-foreground uppercase tracking-widest">{children}</h3>;

function RuleList({ rules }: { rules: any[] }) {
  return (
    <ul className="space-y-1.5">
      {rules.map((r) => (
        <li key={r.id} className={cn("flex items-start gap-2.5 rounded-lg px-3 py-2 text-sm", TINT[r.level])}>
          <Dot level={r.level} className="mt-1.5" />
          <span><span className="font-medium">{r.label}.</span> <span className="text-muted-foreground">{r.note}</span></span>
        </li>
      ))}
    </ul>
  );
}

function CheckTable({ location, accounts }: { location: any; accounts: any[] }) {
  const fields: string[] = accounts[0]?.checks.map((c: any) => c.field) ?? [];
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-muted/60 text-left text-muted-foreground text-xs">
            <th className="px-3 py-2 font-medium">Data point</th>
            {location && <th className="px-3 py-2 font-medium">Website {location.url && <a className="ml-1 inline-flex items-center gap-0.5 text-primary hover:underline" href={location.url} target="_blank" rel="noreferrer">open <ExternalLink className="size-3" /></a>}</th>}
            {accounts.map((a) => (
              <th key={a.account.account_id} className="px-3 py-2 font-medium">CRM · {a.role}<span className="block font-mono font-normal text-[11px]">{a.account.account_id}</span></th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fields.map((f, i) => (
            <tr key={f} className="border-t">
              <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{f}</td>
              {location && <td className="px-3 py-2">{accounts[0].checks[i].website}</td>}
              {accounts.map((a) => { const c = a.checks.find((x: any) => x.field === f); return (
                <td key={a.account.account_id} className={cn("px-3 py-2", TINT[c.level])}>
                  <span className="flex items-start gap-2"><Dot level={c.level} className="mt-1.5" /><span>{c.crm}<span className="block text-muted-foreground text-xs">{c.note}</span></span></span>
                </td>); })}
            </tr>
          ))}
          <tr className="border-t">
            <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">Revenue / AR</td>
            {location && <td className="px-3 py-2" />}
            {accounts.map((a) => { const open = a.account.lifetime_revenue > 0 && a.account.outstanding_ar > 0; return (
              <td key={a.account.account_id} className={cn("px-3 py-2", open && TINT.yellow)}>
                <span className="font-mono text-[13px]">${(a.account.lifetime_revenue || 0).toLocaleString()} / ${(a.account.outstanding_ar || 0).toLocaleString()}</span>
                <span className="block text-muted-foreground text-xs">{open ? "Open billing: must be preserved" : "No open billing"}</span>
              </td>); })}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function Writes({ actions }: { actions: any[] }) {
  return <>{actions.map((a, i) => (
    <pre key={i} className="mb-2 overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900 p-3 font-mono text-[12.5px] text-slate-100 leading-relaxed">
      <span className="text-teal-300">{a.op === "create" ? "POST /accounts" : `PATCH /accounts/${a.account_id}`}</span>{"\n"}{JSON.stringify(a.fields, null, 1)}
    </pre>))}</>;
}

function Detail({ p, busy, onApprove, onReject, onUndo, onUndoConfirm, onUndoCancel, onReopen }: any) {
  const open = ["pending", "failed", "conflict"].includes(p.status);
  return (
    <motion.section initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.2 }} className="rounded-xl border bg-card shadow-sm">
      <div className={cn("flex flex-wrap items-start justify-between gap-4 rounded-t-xl border-b p-5", TINT[p.verdict])}>
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <VerdictPill verdict={p.verdict} />
            <Status><StatusLabel>{p.kind_label}</StatusLabel></Status>
            {p.status !== "pending" && <Status variant={p.status === "applied" ? "green" : p.status === "rejected" ? "red" : "yellow"}><StatusLabel>{STATUS_LABEL[p.status] ?? p.status}</StatusLabel></Status>}
          </div>
          <h2 className="font-semibold text-xl tracking-tight">{p.title}</h2>
          <p className="mt-1 max-w-[70ch] text-muted-foreground text-sm">{p.summary}</p>
        </div>
        {p.status === "applied" && p.undo && (
          <Button variant="outline" onClick={onUndo} disabled={busy}><Undo2 /> Undo this change…</Button>
        )}
        {open && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={onReject} disabled={busy}><X /> Reject</Button>
            <Button variant={p.verdict === "green" ? "success" : p.verdict === "yellow" ? "warning" : "destructive"} onClick={onApprove} disabled={busy}>
              {p.verdict === "red" ? <ShieldAlert /> : <Check />} {p.verdict === "green" ? "Approve and write" : p.verdict === "yellow" ? "Review and approve" : "Override…"}
            </Button>
          </div>
        )}
      </div>
      <div className="space-y-6 p-5">
        {p.status === "undo_requested" && (
          <div className="rounded-lg border border-amber-500/50 bg-amber-400/15 p-4">
            <p className="flex items-center gap-2 font-semibold text-sm"><TriangleAlert className="size-4" /> Undo requested: step 2 of 2 is still needed. Nothing has changed in the CRM yet.</p>
            <p className="mt-1 text-sm">Reason given by {p.undo?.requested_by} at {p.undo?.requested_at}: <span className="italic">{p.undo?.reason}</span></p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="destructive" onClick={onUndoConfirm} disabled={busy}><Undo2 /> Step 2: confirm the undo…</Button>
              <Button variant="outline" onClick={onUndoCancel} disabled={busy}>Cancel the request</Button>
            </div>
          </div>
        )}
        {p.status === "reversed" && (
          <div className="rounded-lg border border-amber-500/50 bg-amber-400/15 p-4">
            <p className="flex items-center gap-2 font-semibold text-sm"><Undo2 className="size-4" /> This change was reversed in the CRM{p.undo?.reversed_at ? ` at ${p.undo.reversed_at}` : ""}.</p>
            <p className="mt-1 text-sm">Reason: <span className="italic">{p.undo?.reason}</span></p>
            <p className="mt-1 text-muted-foreground text-xs">It will not be proposed again on its own. You can send it back to the queue to decide again.</p>
            <Button className="mt-3" variant="outline" onClick={onReopen} disabled={busy}><RotateCcw /> Send back to review</Button>
          </div>
        )}
        {p.undo && ["applied", "undo_requested"].includes(p.status) && (
          <div><H>If you undo this change</H><UndoPreview undo={p.undo} /></div>
        )}
        <div><H>Safety rules</H><RuleList rules={p.rules} /></div>
        {p.accounts.length > 0 && <div><H>Data point checks</H><CheckTable location={p.location} accounts={p.accounts} /></div>}
        <div className="grid gap-6 lg:grid-cols-2">
          <div><H>Why the tool proposes this</H><ul className="list-disc space-y-1 pl-5 text-sm">{p.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></div>
          <div><H>{p.status === "applied" ? "What was written" : "What approval will write"}</H><Writes actions={p.actions} /></div>
        </div>
        {p.decided_at && <p className="text-muted-foreground text-xs">{STATUS_LABEL[p.status] ?? p.status} by {p.decided_by} at {p.decided_at}{p.reason ? ` · ${p.reason}` : ""}</p>}
      </div>
    </motion.section>
  );
}

function ApproveDialog({ p, minReason, busy, onClose, onConfirm }: any) {
  const [ack, setAck] = useState(false);
  const [reason, setReason] = useState("");
  useEffect(() => { setAck(false); setReason(""); }, [p?.id]);
  if (!p) return null;
  const red = p.verdict === "red";
  const ready = !red || (ack && reason.trim().length >= minReason);
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <div className={cn("mb-1 grid size-11 place-items-center rounded-full", red ? "bg-red-600/10 text-red-700" : "bg-amber-400/20 text-amber-700")}>{red ? <ShieldAlert /> : <TriangleAlert />}</div>
          <AlertDialogTitle>{red ? "The rules advise against this change" : "Check these before approving"}</AlertDialogTitle>
          <AlertDialogDescription>
            {red ? "You can still approve it, but this writes to the CRM against the predefined rules. Your reason is saved in the audit log."
                 : "This change passed the hard rules but has cautions. Confirm you have looked at each one."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div><H>{p.title}</H><RuleList rules={p.cautions} /></div>
        <div><H>This will write</H><Writes actions={p.actions} /></div>
        {red && (
          <div className="space-y-3 rounded-lg border border-red-600/30 bg-red-600/5 p-3">
            <label className="flex cursor-pointer items-start gap-2 text-sm"><input id="ack" type="checkbox" className="mt-1 size-4 accent-red-700" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <span>I checked the website and the CRM records myself, and I want to override the rules.</span></label>
            <div>
              <label htmlFor="why" className="mb-1 block font-medium text-sm">Why is this safe? (at least {minReason} characters)</label>
              <textarea id="why" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: confirmed with the corporate office that this is the surviving record"
                className="w-full rounded-md border bg-card p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
            </div>
          </div>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Go back</AlertDialogCancel>
          <Button variant={red ? "destructive" : "warning"} disabled={!ready || busy} onClick={() => onConfirm(p, red ? { override: true, reason } : { confirm: true })}>
            {red ? "Override and write to CRM" : "Approve and write to CRM"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function RejectDialog({ p, busy, onClose, onConfirm }: any) {
  const [reason, setReason] = useState("");
  useEffect(() => setReason(""), [p?.id]);
  if (!p) return null;
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Reject this proposal?</AlertDialogTitle>
          <AlertDialogDescription>{p.title}. Nothing is written to the CRM, and this exact change will not be proposed again.</AlertDialogDescription>
        </AlertDialogHeader>
        <div>
          <label htmlFor="rej" className="mb-1 block font-medium text-sm">Reason (optional)</label>
          <input id="rej" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: cosmetic spelling difference"
            className="w-full rounded-md border bg-card p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Go back</AlertDialogCancel>
          <Button variant="destructive" disabled={busy} onClick={() => onConfirm(p, reason)}>Reject</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

const STATUS_LABEL: Record<string, string> = { applied: "applied", rejected: "rejected", undo_requested: "undo requested", reversed: "reversed", pending: "pending" };

function UndoPreview({ undo }: { undo: any }) {
  return (
    <div className="space-y-2">
      {undo.preview.map((s: any, i: number) => (
        <div key={i} className="rounded-lg border bg-card p-3 text-sm">
          <p className="font-medium">{s.account}<span className="ml-2 font-mono font-normal text-[11px] text-muted-foreground">{s.account_id}</span></p>
          <p className="text-muted-foreground text-xs">{s.label}</p>
          <ul className="mt-2 space-y-1">{s.changes.map((c: any) => (
            <li key={c.field} className="flex flex-wrap items-center gap-2 font-mono text-[12.5px]">
              <span className="text-muted-foreground">{c.field}</span><span className="rounded bg-red-600/10 px-1.5 py-0.5">{String(c.from ?? "(empty)") || "(empty)"}</span>
              <ArrowRight className="size-3" /><span className="rounded bg-green-600/10 px-1.5 py-0.5">{String(c.to ?? "(empty)") || "(empty)"}</span>
            </li>))}</ul>
        </div>))}
      <p className="text-muted-foreground text-xs">A dated note is added to each account saying what was reversed and why. Earlier notes are kept.</p>
      {undo.related.length > 0 && (
        <div className="rounded-lg border border-amber-500/50 bg-amber-400/15 p-3 text-sm">
          <p className="flex items-center gap-2 font-medium"><TriangleAlert className="size-4" /> Linked approved changes touch the same accounts</p>
          <ul className="mt-1 list-disc pl-5">{undo.related.map((t: string) => <li key={t}>{t}</li>)}</ul>
          <p className="mt-1 text-xs">Undoing only one of a linked set can leave the records inconsistent. Consider whether to undo these too.</p>
        </div>
      )}
    </div>
  );
}

function UndoAskDialog({ p, minReason, busy, onClose, onConfirm }: any) {
  const [reason, setReason] = useState("");
  useEffect(() => setReason(""), [p?.id]);
  if (!p) return null;
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <div className="mb-1 grid size-11 place-items-center rounded-full bg-amber-400/20 text-amber-700"><Undo2 /></div>
          <AlertDialogTitle>Step 1 of 2: ask to undo this change</AlertDialogTitle>
          <AlertDialogDescription>{p.title}. This only files the request. Nothing in the CRM changes until you confirm in step 2.</AlertDialogDescription>
        </AlertDialogHeader>
        <div><H>This is what an undo would do</H><UndoPreview undo={p.undo} /></div>
        <div>
          <label htmlFor="uwhy" className="mb-1 block font-medium text-sm">Why should this be undone? (at least {minReason} characters)</label>
          <textarea id="uwhy" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: the owner confirmed these are two separate facilities"
            className="w-full rounded-md border bg-card p-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Go back</AlertDialogCancel>
          <Button variant="warning" disabled={busy || reason.trim().length < minReason} onClick={() => onConfirm(p, reason.trim())}>Request undo</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function UndoConfirmDialog({ p, busy, onClose, onConfirm }: any) {
  const [typed, setTyped] = useState("");
  const [ack, setAck] = useState(false);
  useEffect(() => { setTyped(""); setAck(false); }, [p?.id]);
  if (!p) return null;
  const ready = typed.trim().toUpperCase() === "UNDO" && ack;
  return (
    <AlertDialog open onOpenChange={(o) => !o && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <div className="mb-1 grid size-11 place-items-center rounded-full bg-red-600/10 text-red-700"><ShieldAlert /></div>
          <AlertDialogTitle>Step 2 of 2: confirm. This writes to the CRM.</AlertDialogTitle>
          <AlertDialogDescription>{p.title}. The reason on file: <span className="italic">{p.undo?.reason}</span></AlertDialogDescription>
        </AlertDialogHeader>
        <div><H>Exactly what will change</H><UndoPreview undo={p.undo} /></div>
        <div className="space-y-3 rounded-lg border border-red-600/30 bg-red-600/5 p-3">
          <label className="flex cursor-pointer items-start gap-2 text-sm"><input id="uack" type="checkbox" className="mt-1 size-4 accent-red-700" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            <span>I have looked at the CRM records, and I want these fields set back. If someone changed them since, the app will refuse and write nothing.</span></label>
          <div>
            <label htmlFor="utype" className="mb-1 block font-medium text-sm">Type UNDO to confirm</label>
            <input id="utype" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" placeholder="UNDO"
              className="w-full rounded-md border bg-card p-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </div>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Go back</AlertDialogCancel>
          <Button variant="destructive" disabled={!ready || busy} onClick={() => onConfirm(p)}>Undo in the CRM</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function Matches({ matches }: { matches: any[] }) {
  return (
    <div className="rounded-xl border bg-card p-5 shadow-sm">
      <p className="mb-4 max-w-[75ch] text-muted-foreground text-sm">Website locations already linked to the right CRM account under the right parent, with nothing to change. Each dot is one data point check.</p>
      <div className="overflow-x-auto"><table className="w-full text-sm">
        <thead><tr className="border-b text-left text-muted-foreground text-xs"><th className="py-2 pr-3 font-medium">Website location</th><th className="py-2 pr-3 font-medium">CRM account</th><th className="py-2 pr-3 font-medium">Checks</th><th className="py-2 font-medium">Verdict</th></tr></thead>
        <tbody>{matches.map((m) => (
          <tr key={m.account.account_id} className="border-b last:border-0">
            <td className="py-2 pr-3"><a className="font-medium text-primary hover:underline" href={m.location.url} target="_blank" rel="noreferrer">{m.location.name}</a><span className="block text-muted-foreground text-xs">{m.location.street}, {m.location.city} {m.location.state}</span></td>
            <td className="py-2 pr-3">{m.account.name}<span className="block font-mono text-[11px] text-muted-foreground">{m.account.account_id}</span></td>
            <td className="py-2 pr-3"><span className="flex flex-wrap gap-1">{m.checks.map((c: any) => <span key={c.field} title={`${c.field}: ${c.note}`}><Dot level={c.level} /></span>)}</span></td>
            <td className="py-2"><VerdictPill verdict={m.verdict} short /></td>
          </tr>))}</tbody>
      </table></div>
    </div>
  );
}

function Rules({ data }: any) {
  const Cell = ({ level, text }: any) => <td className={cn("px-3 py-2 align-top", text && TINT[level])}>{text && <span className="flex items-start gap-2"><Dot level={level} className="mt-1.5" />{text}</span>}</td>;
  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-3">
        {(["green", "yellow", "red"] as Level[]).map((v) => (
          <div key={v} className={cn("rounded-xl border p-4", TINT[v])}><VerdictPill verdict={v} />
            <p className="mt-2 text-sm">{v === "green" ? "Every safety rule is green. One click writes the change." : v === "yellow" ? "At least one caution. The reviewer must confirm in a dialog that lists each caution." : "A rule is red. The reviewer must tick an override and type a reason, which is saved in the audit log."}</p></div>))}
      </div>
      <p className="max-w-[80ch] text-muted-foreground text-sm">The verdict is the worst colour among the safety rules. Data point checks feed those rules; a red data point alone does not block a change, because it is often the thing being fixed. The server enforces the verdict, so it cannot be skipped from the browser.</p>
      {[["Safety rules (decide the verdict)", data.safety_rules, "label"], ["Data point checks (website vs CRM)", data.field_rules, "field"]].map(([title, rows, key]: any) => (
        <div key={title} className="rounded-xl border bg-card p-5 shadow-sm"><H>{title}</H>
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-muted-foreground text-xs"><th className="px-3 py-2 font-medium">{key === "label" ? "Rule" : "Data point"}</th><th className="px-3 py-2 font-medium">Green</th><th className="px-3 py-2 font-medium">Yellow</th><th className="px-3 py-2 font-medium">Red</th></tr></thead>
            <tbody>{rows.map((r: any) => <tr key={r[key]} className="border-t"><td className="whitespace-nowrap px-3 py-2 font-medium">{r[key]}</td><Cell level="green" text={r.green} /><Cell level="yellow" text={r.yellow} /><Cell level="red" text={r.red} /></tr>)}</tbody></table></div>
        </div>))}
    </div>
  );
}

function Activity({ data }: any) {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="rounded-xl border bg-card p-5 shadow-sm"><H>Pipeline runs</H>
        <table className="w-full text-sm"><thead><tr className="text-left text-muted-foreground text-xs"><th className="py-2 font-medium">#</th><th className="py-2 font-medium">Started (UTC)</th><th className="py-2 font-medium">Scraped</th><th className="py-2 font-medium">New</th><th className="py-2 font-medium">Skipped, decided</th></tr></thead>
          <tbody>{data.runs.map((r: any) => <tr key={r.id} className="border-t"><td className="py-2 font-mono">{r.id}</td><td className="py-2">{r.started_at}</td><td className="py-2">{r.locations}</td><td className="py-2">{r.new_proposals}</td><td className="py-2">{r.skipped_decided}</td></tr>)}</tbody></table></div>
      <div className="rounded-xl border bg-card p-5 shadow-sm"><H>Audit log</H>
        {data.audit.length === 0 ? <p className="text-muted-foreground text-sm">No decisions yet.</p> : <ul className="space-y-2 text-sm">{data.audit.map((a: any) => (
          <li key={a.id} className="flex items-start gap-2 border-t pt-2 first:border-0 first:pt-0"><Dot level={a.event === "applied" ? "green" : a.event === "rejected" || a.event === "override" || a.event === "undo_failed" ? "red" : "yellow"} className="mt-1.5" />
            <span><span className="font-medium">{a.event}</span> · {a.title}<span className="block text-muted-foreground text-xs">{a.actor} · {a.at}{["override", "undo_requested", "undo_conflict", "undo_failed"].includes(a.event) && a.detail ? ` · ${a.event === "override" || a.event === "undo_requested" ? "reason" : "detail"}: ${a.detail}` : ""}</span></span></li>))}</ul>}
      </div>
    </div>
  );
}
