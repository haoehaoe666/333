import json
import time
import argparse
import os
import logging
import datetime

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
)

from utils import reserve, get_user_credentials

SLEEPTIME = 0.2  # 每次抢座失败重试的间隔
ENDTIME = "20:01:00"  # 结束时间

ENABLE_SLIDER = True  # 是否启用滑块验证码
MAX_ATTEMPT = 3  # 最大尝试次数
RESERVE_NEXT_DAY = False  # 是否预约明天


def prepare_sessions(users, action):
    """预热阶段：20:00 前完成账号登录并初始化 Session"""
    usernames, passwords = None, None
    if action:
        usernames, passwords = get_user_credentials(action)

    current_dayofweek = (
        (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%A")
        if action
        else time.strftime("%A")
    )

    runners = []

    for index, user in enumerate(users):
        username, password, times, roomid, seatid, daysofweek = user.values()
        if type(seatid) == str:
            seatid = [seatid]

        if action:
            username = usernames.split(",")[index]
            password = passwords.split(",")[index]

        if current_dayofweek not in daysofweek:
            logging.info(f"User {username}: Today ({current_dayofweek}) not set to reserve, skip.")
            continue

        # 实例化 reserve 类并提前登录
        s = reserve(
            sleep_time=SLEEPTIME,
            max_attempt=MAX_ATTEMPT,
            enable_slider=ENABLE_SLIDER,
            reserve_next_day=RESERVE_NEXT_DAY,
        )
        s.get_login_status()
        s.login(username, password)
        s.requests.headers.update({"Host": "office.chaoxing.com"})

        runners.append({
            "session": s,
            "username": username,
            "times": times,
            "roomid": roomid,
            "seatid": seatid,
            "action": action
        })

    return runners


def main(users, action=False):
    logging.info(
        f"Global settings: \nSLEEPTIME: {SLEEPTIME}\nENDTIME: {ENDTIME}\nENABLE_SLIDER: {ENABLE_SLIDER}\nRESERVE_NEXT_DAY: {RESERVE_NEXT_DAY}"
    )

    # 第一步：20:00:00 前提前登录
    logging.info("正在进行账号登录与 Session 预热...")
    runners = prepare_sessions(users, action)
    if not runners:
        logging.info("今日没有符合条件的预约任务，退出程序。")
        return

    # 标记位，控制预热逻辑只触发一次
    captcha_pre_fetched = False
    token_pre_fetched = False

    # 第二步：精准倒计时循环
    logging.info("进入精准等待循环，目标时间：北京时间 20:00:00...")
    while True:
        # 获取北京时间 (UTC+8)
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)

        # 阶段 1：19:59:55 秒（或之后）提前解算滑块验证码
        if not captcha_pre_fetched and (
            now.hour > 19 or (now.hour == 19 and now.minute == 59 and now.second >= 55)
        ):
            logging.info("⏱️ 到达 19:59:55，开始提前解算滑块验证码...")
            for runner in runners:
                runner["session"].pre_fetch_captcha()
            captcha_pre_fetched = True

        # 阶段 2：19:59:59 秒（或之后）提前拉取页面 Token
        if not token_pre_fetched and (
            now.hour > 20 or (now.hour == 20 and now.minute == 0 and now.second >= 5)
        ):
            logging.info("⏱️ 到达 19:59:59，开始提前拉取页面 Token...")
            for runner in runners:
                runner["session"].pre_fetch_page_token(runner["roomid"], runner["seatid"][0])
            token_pre_fetched = True

        # 阶段 3：20:00:00 秒到达，直接跳出等待，发起极速提交
        if now.hour >= 20:
            logging.info(f"🚀 到达预定时间: {now.strftime('%H:%M:%S.%f')[:-3]}，启动极速发包提交！")
            break

        time.sleep(0.01)  # 10ms 高精度轮询

    # 第三步：执行预约发包
    success_flags = [False] * len(runners)
    attempt_times = 0

    while True:
        attempt_times += 1
        now_str = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%H:%M:%S")

        if now_str >= ENDTIME:
            logging.info("已达到设定结束时间，停止尝试。")
            break

        for idx, runner in enumerate(runners):
            if not success_flags[idx]:
                logging.info(f"----------- {runner['username']} -- {runner['times']} -- {runner['seatid']} 第 {attempt_times} 次提交 -----------")
                suc = runner["session"].submit(
                    times=runner["times"],
                    roomid=runner["roomid"],
                    seatid=runner["seatid"],
                    action=runner["action"]
                )
                success_flags[idx] = suc

        if all(success_flags):
            logging.info("🎉 所有人预约成功！程序退出。")
            return

        time.sleep(SLEEPTIME)


def debug(users, action=False):
    logging.info("Debug Mode Start!")
    runners = prepare_sessions(users, action)
    for runner in runners:
        runner["session"].submit(
            times=runner["times"],
            roomid=runner["roomid"],
            seatid=runner["seatid"],
            action=runner["action"]
        )


def get_roomid(args1, args2):
    username = input("请输入用户名：")
    password = input("请输入密码：")
    s = reserve(
        sleep_time=SLEEPTIME,
        max_attempt=MAX_ATTEMPT,
        enable_slider=ENABLE_SLIDER,
        reserve_next_day=RESERVE_NEXT_DAY,
    )
    s.get_login_status()
    s.login(username=username, password=password)
    s.requests.headers.update({"Host": "office.chaoxing.com"})
    encode = input("请输入deptldEnc：")
    s.roomid(encode)


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    parser = argparse.ArgumentParser(prog="Chao Xing seat auto reserve")
    parser.add_argument("-u", "--user", default=config_path, help="user config file")
    parser.add_argument(
        "-m",
        "--method",
        default="reserve",
        choices=["reserve", "debug", "room"],
        help="for debug",
    )
    parser.add_argument(
        "-a",
        "--action",
        action="store_true",
        help="use --action to enable in github action",
    )
    args = parser.parse_args()
    func_dict = {"reserve": main, "debug": debug, "room": get_roomid}

    with open(args.user, "r+") as data:
        usersdata = json.load(data)["reserve"]

    func_dict[args.method](usersdata, args.action)
