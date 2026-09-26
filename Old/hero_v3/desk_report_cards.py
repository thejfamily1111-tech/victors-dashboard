"""Read-only empirical comparisons from v3 journals; no synthetic performance."""
import argparse,json
import learn_tracker as lt

def main():
    p=argparse.ArgumentParser();p.add_argument('--events',default=str(lt.LEARN_LOG_FILE));p.add_argument('--outcomes',default=str(lt.OUTCOME_FILE))
    a=p.parse_args()
    print(json.dumps(lt.json_safe(lt.comparison_report(lt.read_events(a.events),lt.read_events(a.outcomes))),indent=2,allow_nan=False))

if __name__=='__main__':main()
