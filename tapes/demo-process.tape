# covtest process demo — run after a full test suite
# Run with: vhs tapes/demo-process.tape

Output docs/assets/demo-process.gif

Set FontSize 14
Set Width 100
Set Height 28
Set Theme "Catppuccin Mocha"
Set Padding 20
Set PlaybackSpeed 0.8

Type "# Step 1: run the full suite with coverage contexts"
Sleep 800ms
Enter
Sleep 300ms

Type "pytest --cov=mypackage --cov-context=test"
Sleep 500ms
Enter
Sleep 3s

Type "# Step 2: build the covtest snapshot"
Sleep 800ms
Enter
Sleep 300ms

Type "covtest process -v"
Sleep 500ms
Enter
Sleep 5s

Type "# Snapshot saved. Ready to predict."
Sleep 1s
Enter
Sleep 800ms

Type "ls .covtest/"
Sleep 300ms
Enter
Sleep 800ms
