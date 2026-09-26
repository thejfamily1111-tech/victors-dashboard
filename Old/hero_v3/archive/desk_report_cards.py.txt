"""
desk_report_cards.py
Institutional Performance & Attribution Auditor for HERO and VIC.
Calculates statistical expectancy, false rejection rates, and net veto value.
"""

import os
import pandas as pd
import numpy as np
import learn_tracker as lt

def generate_report_cards():
    df = lt.load_eval_dataframe()
    if df.empty:
        print("⚪ No observation data found in hero_eval_records.jsonl.")
        return

    # Filter strictly for resolved observations
    resolved_mask = df["outcome.resolved"] == True
    df_res = df[resolved_mask].copy()

    if df_res.empty:
        print(f"⚪ Found {len(df)} records, but none are resolved yet. Run resolve_daily_candidates.py first.")
        return

    print("\n" + "=" * 65)
    print("🏛️  QUANTITATIVE DESK AUDIT & ATTRIBUTION REPORT CARDS")
    print("=" * 65)

    # -------------------------------------------------------------
    # 1. HERO TACTICAL HUNTER REPORT CARD
    # -------------------------------------------------------------
    hero_approved = df_res[df_res["hero.decision"] == "APPROVE"]
    hero_rejected = df_res[df_res["hero.decision"] == "REJECT"]

    n_approved = len(hero_approved)
    print(f"\n[ HERO V1.0 - Tactical Hunter ]")
    print(f"Total Evaluated Setups: {len(df_res)}")
    print(f"Approved Candidates:    {n_approved}")

    if n_approved > 0:
        r_vals = hero_approved["outcome.underlying_result_r"].astype(float)
        wins = r_vals[r_vals > 0]
        losses = r_vals[r_vals < 0]

        win_rate = len(wins) / n_approved
        avg_win = wins.mean() if len(wins) > 0 else 0.0
        avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0
        expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss)

        gross_gains = wins.sum() if len(wins) > 0 else 0.0
        gross_losses = abs(losses.sum()) if len(losses) > 0 else 0.0
        profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else np.nan

        p_plus_1r = hero_approved["outcome.hit_plus_1r"].mean() * 100.0
        p_plus_2r = hero_approved["outcome.hit_plus_2r"].mean() * 100.0
        mean_mfe = hero_approved["outcome.mfe_r"].astype(float).mean()
        mean_mae = hero_approved["outcome.mae_r"].astype(float).mean()

        print(f"  • Mathematical Expectancy: {expectancy:+.2f}R per setup")
        print(f"  • Profit Factor:           {profit_factor:.2f}" if not np.isnan(profit_factor) else "  • Profit Factor:           N/A (No Losses)")
        print(f"  • Win Rate:                {win_rate * 100:.1f}% ({len(wins)}W / {len(losses)}L)")
        print(f"  • Avg Win / Avg Loss:      +{avg_win:.2f}R / -{avg_loss:.2f}R")
        print(f"  • Median Result:           {r_vals.median():+.2f}R")
        print(f"  • Mean MFE / MAE:          +{mean_mfe:.2f}R / {mean_mae:.2f}R")
        print(f"  • Touch +1R Rate:          {p_plus_1r:.1f}%")
        print(f"  • Touch +2R Rate:          {p_plus_2r:.1f}%")

    # False Rejection Rate Audit
    n_rejected = len(hero_rejected)
    if n_rejected > 0:
        false_rejects = hero_rejected[hero_rejected["outcome.plus_2r_before_minus_1r"] == True]
        false_reject_rate = (len(false_rejects) / n_rejected) * 100.0
        print(f"\n  [ Counterfactual Rejection Audit ]")
        print(f"  • Total Rejected Setups:   {n_rejected}")
        print(f"  • False Rejections (+2R):  {len(false_rejects)}")
        print(f"  • False Rejection Rate:    {false_reject_rate:.1f}% (Lower is better)")
    else:
        print(f"\n  • Rejected Setups Sample:  0 (Awaiting rejection observations)")

    # -------------------------------------------------------------
    # 2. VIC RISK GOVERNOR REPORT CARD
    # -------------------------------------------------------------
    vetoed = df_res[df_res["vic.verdict"] == "VETO"]
    downgraded = df_res[df_res["vic.verdict"] == "DOWNGRADE"]

    print(f"\n[ VIC V1.0 - Macro Risk Governor ]")
    print(f"Total Macro Audits:     {len(df_res)}")
    print(f"Vetoes Issued:          {len(vetoed)}")
    print(f"Downgrades Issued:      {len(downgraded)}")

    if len(vetoed) > 0:
        cf_r_veto = vetoed["outcome.counterfactual_result_r"].astype(float)
        losses_avoided = (cf_r_veto < 0).sum()
        winners_blocked = (cf_r_veto > 0).sum()
        
        # VIC Net Contribution: -Mean(Counterfactual R of vetoes)
        # If vetoed setups average -0.50R, VIC adds +0.50R of value per veto.
        vic_net_contrib = -cf_r_veto.mean()

        print(f"  • Losses Avoided:          {losses_avoided} (True Positives)")
        print(f"  • Winners Blocked:         {winners_blocked} (False Positives)")
        print(f"  • Net Veto Contribution:   {vic_net_contrib:+.2f}R per veto")
        if vic_net_contrib > 0:
            print(f"  • Governor Alpha Status:   ✅ ACCRETIVE (Filtering toxic trades)")
        else:
            print(f"  • Governor Alpha Status:   ⚠️ DRAG (Vetoing profitable momentum)")
    else:
        print(f"  • Veto Audit Sample:       0 (No vetoes encountered in resolved sample)")

    print("\n" + "=" * 65 + "\n")

if __name__ == "__main__":
    generate_report_cards()