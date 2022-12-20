from flask import Flask,redirect,request,render_template,url_for,make_response
from ansi2html import Ansi2HTMLConverter
from concurrent.futures import as_completed
#from requests_futures.sessions import FuturesSession
import random, json, os, time, redis, subprocess, requests, archey

#設定資料庫
REDIS = redis.Redis(
  host= 'usw2-stable-sunfish-30320.upstash.io',
  port= '30320',
  password= 'ef2629d1f9ee4d61bf9b41bf6c738da0',
  decode_responses=True
)

class data:
    def __init__(self) -> None:
        self.cookie_dict = {}
        self.url_dict = {}
        self.galgame_file_ID_dict = {}
 

#讀取環境變數
def read_data() -> data:
    print('讀取資料中...')
    if os.path.isfile('/tmp/data'):
        print('存在緩存資料...')
        f = open('/tmp/data')
        data = json.loads(f.read())
        print('讀取緩存資料...')
        f.close()
        if data['TIME'] < (time.time()-432000):
            print('緩存過期...')
            data = json.loads(REDIS.get('henryapi_data'))
            print('線上取得資料...')
            T = time.time()
            data['TIME']= T
            with open('/tmp/data', 'w') as f:
                print('寫入緩存...')
                f.write(json.dumps(data))
        print('成功讀取資料')
    else:
        print('不存在緩存資料...')
        data = json.loads(REDIS.get('henryapi_data'))
        print('線上取得資料...')
        T = time.time()
        data['TIME']= T
        with open('/tmp/data', 'w') as f:
            print('寫入緩存...')
            f.write(json.dumps(data))
        print('成功讀取資料')


    cookie_list = data['cookie_list']
    galgame_file_root_url = data['galgame_file_root_url']
    random_h_anime_pic_url = data['random_h_anime_pic_url']
    galgame_file_ID = data['galgame_file_ID']
    return cookie_list,galgame_file_root_url,random_h_anime_pic_url,galgame_file_ID,data




app = Flask(__name__)

@app.route("/")
def index():
    conv = Ansi2HTMLConverter()
    ansi = "".join(subprocess.check_output('archey',text=True))
    #print(subprocess.check_output('archey',text=True))
    html = conv.convert(ansi)
    return html

@app.route("/clc")
def clc():
    print('刪除 /tmp/data 中...')
    os.remove('/tmp/data')
    print('已刪除')
    data = json.loads(REDIS.get('henryapi_data'))
    print('變數已更新')
    data['TIME'] = time.time()
    with open('/tmp/data', 'w') as f:
        f.write(json.dumps(data))
    print('/tmp/data 已重新儲存')
    return 'success'

#已廢棄
'''
def get_respons_time(urls):
    response_times = []
    with FuturesSession() as session:
        futures = [session.get(url) for url in urls]
        for future in as_completed(futures):
            res = future.result()
            response_times.append(res.elapsed.total_seconds())
    return response_times

@app.route('/monitor/')
@app.route('/monitor')
def monitor():
    (cookie_list,galgame_file_root_url,random_h_anime_pic_url,galgame_file_ID,data) = read_data()
    os.system('curl -so /dev/null -w "%{time_total}\\n" https://henryapi.azurewebsites.net/ > /home/t.txt')
    with open('/home/t.txt','r') as f:_time = float(f.read())
    url_name_list = data['url_name_list']
    url_list = data['url_list']
    response_time_data = REDIS.get('response_time_data')
    if response_time_data and json.loads(response_time_data)['time'] > time.time() - 60:
        response_time_dic = json.loads(response_time_data)['response_time_dic']
        response_times = [response_time_dic[x] for x in response_time_dic]
    else:
        response_times = get_respons_time(url_list)
        response_time_dic = {url_list[i]:response_times[i] for i in range(len(url_list))}
        response_time_data = {'time':float(time.time()),'response_time_dic':response_time_dic}
        REDIS.set('response_time_data',json.dumps(response_time_data))

    ret = '<!DOCTYPE html><head><title>監視器</title></head><body><div style="display: flex;width: 100%;word-wrap:break-word"><div style="margin-right: 5%;"><table><thead><tr><th colspan="'+str(len(url_list))+'">各地回應速度</th></tr></thead><tbody><tr><td>'+'HenryAPI'+'</td><td>'+str(_time)+'</td></tr>'
    for i in range(len(url_list)):
        ret += '<tr><td>'
        ret += str(url_name_list[i])
        ret += '</td><td>'
        ret += str(response_times[i])
        ret += '</td></tr>'
    Location = json.loads(requests.get('https://ipinfo.io').text)
    ret += '</tbody></table></div><div><br><br><br><br>CPU usage %: '+str(psutil.cpu_percent(4))+'<br><br>RAM usage %: '+str(psutil.virtual_memory()[2])+'<br><br>RAM used GB: '+str(psutil.virtual_memory()[3]/1000000000)+'<br><br>IP: '+str(Location['ip'])+'<br><br>Location: '+str(Location['country'])+', '+str(Location['region'])+', '+str(Location['city'])
    return ret
'''

@app.route("/api/")
@app.route("/api")
def api():
    return render_template('api.html')

@app.route("/api/onedrive/")
@app.route("/api/onedrive")
def api_onedrive():
    (cookie_list,galgame_file_root_url,random_h_anime_pic_url,galgame_file_ID,data) = read_data()
    cookie_list = json.loads(REDIS.get('henryapi_data'))['cookie_list']
    type_list = ['galgame']
    downloader_list = ['aria2c','wget','ps','curl']
    type_ = request.args.get('type')
    file_SN_ = request.args.get('sn')
    downloader_ = request.args.get('downloader')
    if file_SN_ in ['tools','Tools','tool','Tool','TOOLS','TOOL']:
        return redirect('https://mailswdpsntpcedutw-my.sharepoint.com/:u:/g/personal/s96281_mails_wdps_ntpc_edu_tw/Ee6j5jE-HftBtA6vgjNlffEBzu_t4bx0jHEu6lH0mUklFQ?download=1')
    if (type_ in type_list) and (file_SN_ in galgame_file_ID) and (downloader_ in downloader_list):
        if type_ == 'galgame':
            cookie_str = cookie_list['s96281mailswdpsntpcedutw']
            command = 'wget --header="cookie:'+cookie_str+'" '+galgame_file_root_url+galgame_file_ID[file_SN_].replace('-','%2D')+' -O '+file_SN_+'.rar'
            if downloader_ == 'aria2':
                command = 'aria2c -x 1 --header=cookie:"'+cookie_str+'" '+galgame_file_root_url+galgame_file_ID[file_SN_].replace('-','%2D')
            elif downloader_ == 'curl':
                command = 'curl -v --cookie "'+cookie_str+'" '+galgame_file_root_url+galgame_file_ID[file_SN_].replace('-','%2D')+' -o '+file_SN_+'.rar'
            elif downloader_ == 'ps':
                command = '$ProgressPreference="SilentlyContinue";$downloadToPath="./'+file_SN_+'.rar'+'";$remoteFileLocation="'+galgame_file_root_url+galgame_file_ID[file_SN_].replace('-','%2D')+'";$session=New-Object Microsoft.PowerShell.Commands.WebRequestSession;$cookie=New-Object System.Net.Cookie;$cookie.Name="'+cookie_str.split(';')[0].split('=')[0]+'";$cookie.Value="'+cookie_str.split(';')[0].split('=')[1]+'";$cookie.Domain ="sharepoint.com";$session.Cookies.Add($cookie);$cookie.Name="'+cookie_str.split(';')[1].split('=')[0].replace(' ','')+'";$cookie.Value="'+cookie_str.split(';')[1].split('=')[1]+'";$cookie.Domain ="sharepoint.com";$session.Cookies.Add($cookie);Invoke-WebRequest $remoteFileLocation -WebSession $session -TimeoutSec 900 -OutFile $downloadToPath;$ProgressPreference = "Continue"'
        return render_template('get_command.html', command = command)
    return render_template('api_onedrive.html')

@app.route("/api/animepic/")
@app.route("/api/animepic")
def api_animepic():
    (cookie_list,galgame_file_root_url,random_h_anime_pic_url,galgame_file_ID,data) = read_data()
    r18 = request.args.get('h')
    if r18:
        pic_name = str(random.randrange(1,1852)).zfill(4)+'.jpg'
        return render_template('image.html', pic_url = random_h_anime_pic_url + pic_name, title = pic_name)

@app.route("/api/yande.re/")
@app.route("/api/yande.re")
def api_yande_re():
    rating = request.args.get('rating')
    id = request.args.get('id')
    if id:
        rating = json.loads(requests.get('https://yande.re/post.json?tags=id%3A'+str(id)).text)
        if len(rating) != 0:
            rating = rating[0]['rating']
        if rating == 'e':
            url_prefix= 'https://dev.azure.com/ffckmbenmu/699f869b-48b1-45bc-bac1-b815cde22343/_apis/tfvc/items?path=%24/yande.re.e/R18/'
        elif rating == 'q':
            url_prefix= 'https://dev.azure.com/ffckmbenmu/699f869b-48b1-45bc-bac1-b815cde22343/_apis/tfvc/items?path=%24/yande.re.q/'
        else:
            url_prefix= 'https://dev.azure.com/ffckmbenmu/699f869b-48b1-45bc-bac1-b815cde22343/_apis/tfvc/items?path=%24/yande.re.s/'
        url_suffix = '&versionDescriptor%5BversionOptions%5D=0&versionDescriptor%5BversionType%5D=5&versionDescriptor%5Bversion%5D=&%24format=octetStream&api-version=5.0'
        path = (int(id)//20000+1)*20000
        return render_template('image_auth.html', pic_url = url_prefix + str(path) + '/' + str(id) + '.jpg' + url_suffix, title = str(id)+'.jpg')
        
    if rating == 'e' or rating == 'explicit' :
        url_prefix= 'https://dev.azure.com/ffckmbenmu/699f869b-48b1-45bc-bac1-b815cde22343/_apis/tfvc/items?path=%24/yande.re.e/R18/'
        url_suffix = '&versionDescriptor%5BversionOptions%5D=0&versionDescriptor%5BversionType%5D=5&versionDescriptor%5Bversion%5D=&%24format=octetStream&api-version=5.0'
        with open('yande.re.e.txt','r') as f:
            yande_re_list = json.loads(f.read())
        pic_name = yande_re_list[random.randrange(0,len(yande_re_list))]
        path = (pic_name//20000+1)*20000
        return render_template('image_auth.html', pic_url = url_prefix + str(path) + '/' + str(pic_name) + '.jpg' + url_suffix, title = str(pic_name)+'.jpg')
    elif rating == 'q' or rating == 'questionable':
        url_prefix= 'https://dev.azure.com/ffckmbenmu/699f869b-48b1-45bc-bac1-b815cde22343/_apis/tfvc/items?path=%24/yande.re.q/'
        url_suffix = '&versionDescriptor%5BversionOptions%5D=0&versionDescriptor%5BversionType%5D=5&versionDescriptor%5Bversion%5D=&%24format=octetStream&api-version=5.0'
        with open('yande.re.q.txt','r') as f:
            yande_re_list = json.loads(f.read())
        pic_name = yande_re_list[random.randrange(0,len(yande_re_list))]
        path = (pic_name//20000+1)*20000
        return render_template('image_auth.html', pic_url = url_prefix + str(path) + '/' + str(pic_name) + '.jpg' + url_suffix, title = str(pic_name)+'.jpg')
    url_prefix= 'https://dev.azure.com/ffckmbenmu/699f869b-48b1-45bc-bac1-b815cde22343/_apis/tfvc/items?path=%24/yande.re.s/'
    url_suffix = '&versionDescriptor%5BversionOptions%5D=0&versionDescriptor%5BversionType%5D=5&versionDescriptor%5Bversion%5D=&%24format=octetStream&api-version=5.0'
    with open('yande.re.s.txt','r') as f:
        yande_re_list = json.loads(f.read())
    pic_name = yande_re_list[random.randrange(0,len(yande_re_list))]
    path = (pic_name//20000+1)*20000
    return render_template('image_auth.html', pic_url = url_prefix + str(path) + '/' + str(pic_name) + '.jpg' + url_suffix, title = str(pic_name)+'.jpg')


@app.route("/school",methods=['POST','GET'])
def school():
    user = request.args.get('user')
    if 'username' in requests.values:
        user = requests.form.get('username')
        print('參數USER='+user)
        return redirect(url_for('school',user = user))

    if not user:
        return render_template('inputusername.html')
    else:
        images = json.loads(REDIS.get('images'))
        score_list = json.loads(REDIS.get('score_list'))
        users = []
        scores = []
        if user in score_list:
            score_list = {k: v for k, v in sorted(score_list.items(), key=lambda item: item[1],reverse=True)}
            for u in score_list:
                users.append(u)
                scores.append(score_list[u])
        else:
            score_list[user] = 0
            score_list = {k: v for k, v in sorted(score_list.items(), key=lambda item: item[1],reverse=True)}
            REDIS.set('score_list',json.dumps(score_list))
            for u in score_list:
                users.append(u)
                scores.append(score_list[u])


    if requests.method =='POST':
        if '正確' in requests.values:
            score_list = json.loads(REDIS.get('score_list'))
            score_list[user] = score_list[user] + 1
            REDIS.set('score_list',json.dumps(score_list))
            return render_template('python程式設計與資料分析.html',TEXT='正確')
        else:
            score_list = json.loads(REDIS.get('score_list'))
            score_list[user] = score_list[user] - 1
            REDIS.set('score_list',json.dumps(score_list))
            ans = requests.cookies.get('answer')
            return render_template('python程式設計與資料分析.html',TEXT='錯誤',answer = ans)


    score1 = scores[0]
    score2 = scores[1]
    score3 = scores[2]
    score4 = scores[3]
    score5 = scores[4]
    user1 = users[0]
    user2 = users[1]
    user3 = users[2]
    user4 = users[3]
    user5 = users[4]
    image_name = images[random.randint(0,len(images))-1]
    image = 'https://henry010125.github.io/animal-plant-illu/'+image_name+'.jpg'
    y = [images[random.randint(0,len(images))-1],images[random.randint(0,len(images))-1],images[random.randint(0,len(images))-1],images[random.randint(0,len(images))-1]]
    x=['錯誤','錯誤','錯誤','錯誤']
    correct_point = random.randint(0,3)
    x[correct_point]='正確'
    y[correct_point]=image_name
    [a,b,c,d] = x
    [A,B,C,D] = y
    resp = make_response(render_template('python程式設計與資料分析.html',TEXT='',score1=score1,user1=user1,score2=score2,user2=user2,score3=score3,user3=user3,score4=score4,user4=user4,score5=score5,user5=user5,image = image,a=a,b=b,c=c,d=d,A=A,B=B,C=C,D=D))
    resp.set_cookie('answer',image_name)
    return resp


if __name__ == '__main__':
    app.run()