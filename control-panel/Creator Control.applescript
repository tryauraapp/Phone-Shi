on run
	set projectRoot to "/Users/lucapritchard/claude-code/Phone-Shi"
	set panelURL to "http://127.0.0.1:8790/"
	set healthURL to "http://127.0.0.1:8790/api/bootstrap"
	set serverScript to projectRoot & "/control-panel/server.py"
	set logFile to projectRoot & "/control-panel/data/server.log"
	set dataFolder to projectRoot & "/control-panel/data"
	set checkCommand to "/usr/bin/curl -fsS --max-time 1 " & quoted form of healthURL & " >/dev/null"

	try
		do shell script checkCommand
	on error
		set launchCommand to "/bin/mkdir -p " & quoted form of dataFolder & "; " & ¬
			"export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin; " & ¬
			"/usr/bin/nohup python3 " & quoted form of serverScript & " --port 8790 >>" & quoted form of logFile & " 2>&1 </dev/null &"
		do shell script launchCommand

		repeat 40 times
			delay 0.1
			try
				do shell script checkCommand
				exit repeat
			end try
		end repeat
	end try

	open location panelURL
end run
