import argparse
from pixhawk import Pixhawk
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--connection', required = True)
    parser.add_argument('--profile', choices=['hitl', 'hardware'], required=True)
    args = parser.parse_args()
    drone = Pixhawk(args.connection, args.profile)
    try:
        while True:
            text = input("UAV>").strip().lower()
            if text == "":
                continue
            elif text == "exit":
                print("Exiting...")
                break
            elif text == "help":
                print("help, status, exit")
            elif text == "status":
                print("Status:", drone.status())
            else:
                print("Lenh chua duoc ho tro:", text)
    finally:
        drone.close()
if __name__ == "__main__":
    main()