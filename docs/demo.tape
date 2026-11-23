# Terminal demo for the README. Regenerate with:
#   brew install vhs && uv sync && vhs docs/demo.tape
# The recording terminal has no image protocol, so billcode draws the codes
# with Unicode blocks (kitty / iTerm2 / WezTerm show real images).

Output docs/demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1680
Set Height 820
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

Env KITTY_WINDOW_ID ""
Env TERM "xterm-256color"

Hide
Type "source .venv/bin/activate && export PS1='$ ' && cd examples && clear"
Enter
Show

Sleep 500ms
Type "billcode esimerkkilasku.pdf"
Sleep 400ms
Enter
Sleep 6s

Type "clear"
Enter
Type "billcode esimerkkilasku.pdf --no-image --svg -o tulosteet   # print-size SVGs"
Sleep 400ms
Enter
Sleep 3s
Type "billcode esimerkkilasku.pdf --no-image --json | jq -r .code"
Sleep 400ms
Enter
Sleep 4s

Hide
Type "rm -rf tulosteet"
Enter
