from wfcommons.wfperf.perf import WorkflowBenchmark
from wfcommons.wfchef.recipes import BlastRecipe
import pathlib
import argparse

this_dir = pathlib.Path(__file__).resolve().parent

def get_parser() ->  argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--path", help="Path to JSON")
    parser.add_argument("-c", "--create", action="store_true", help="Generate Workflow Benchmark when set.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Prints status information when set to true.")
    parser.add_argument("-s", "--save", help="Path to save directory.")
    parser.add_argument("-t", "--num-tasks", help="Number os tasks when create is true.")

    return parser


def main():
    parser = get_parser()
    args = parser.parse_args()
    savedir = pathlib.Path(args.save)
   
    if args.path:
        path = pathlib.Path(args.path)
    num_tasks = int(args.num_tasks)

    print("Running")

    bench = WorkflowBenchmark(BlastRecipe, num_tasks)

    if args.create:
        
        if args.verbose:
            print("Creating Recipe...")
        json_path = bench.create(str(savedir), percent_cpu=0.5, percent_mem=0.3, percent_io=0.2, verbose=True)
        
    else:
        json_path = bench.create(str(savedir), create=False, path=path, verbose=True)

    bench.run(json_path, savedir)



    

    
    
if __name__ == "__main__":
    main()