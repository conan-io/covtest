# covtest predict demo
# Run with: vhs tapes/demo-predict.tape

Output docs/assets/demo-predict.gif

Set FontSize 14
Set Width 100
Set Height 28
Set Theme "Catppuccin Mocha"
Set Padding 20
Set PlaybackSpeed 0.8

# Show the starting state
Type "# Working in a large Python project..."
Sleep 1s
Enter
Sleep 500ms

Type "git diff --stat HEAD"
Sleep 500ms
Enter
Sleep 1s

Type "# 1 file changed — which tests do we need?"
Sleep 1s
Enter
Sleep 500ms

Type "covtest predict -v"
Sleep 500ms
Enter
Sleep 3500ms

Type "cat .covtest/covtests.tests"
Sleep 300ms
Enter
Sleep 800ms

Type "pytest @.covtest/covtests.tests -v"
Sleep 500ms
Enter
Sleep 3s
