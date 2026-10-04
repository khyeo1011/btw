" Vim syntax file for btw. Same categories as the TextMate grammar
" (Implementation Spec 12.2). Multi-word keywords allow any run of spaces or
" tabs between words.

if exists("b:current_syntax")
  finish
endif

" Numbers first, so the 404 match defined later wins at the same position.
syn match btwNumber "\<\d\+\>"

syn match btwDirective "\<i[ \t]\+use[ \t]\+arch[ \t]\+btw\>"
syn match btwDirective "\<localhost:\d\+"
syn match btwDirective ":wq\>"
syn keyword btwDirective serve

syn match btwConditional "\<vibe[ \t]\+check\>"
syn match btwConditional "\<skill[ \t]\+issue\>"
syn match btwRepeat "\<touch[ \t]\+grass\>"
syn keyword btwRepeat doomscroll
syn match btwReturn "\<ship[ \t]\+it\>"

" Shortest first: a later match starting at the same column wins.
syn match btwStorage "\<npm[ \t]\+install\>"
syn match btwStorage "\<npm[ \t]\+install[ \t]\+-g\>"

syn match btwOther "\<git[ \t]\+push[ \t]\+--force\>"
syn match btwOther "\<git[ \t]\+revert\>"
syn match btwOther "\<git[ \t]\+log\>"
syn match btwOther "\<git[ \t]\+blame\>"
syn keyword btwOther sudo

syn match btwConsoleLog "\<console\.log\>"
syn keyword btwConsoleLog curl

syn keyword btwBoolean LGTM
syn match btwBoolean "\<404\d\@!"

" microservice NAME(params) O(...): name and Big O annotation are chained.
syn keyword btwStorage microservice nextgroup=btwFuncName skipwhite
syn match btwFuncName "\h\w*" contained nextgroup=btwParams skipwhite
syn region btwParams start="(" end=")" contained transparent contains=NONE nextgroup=btwBigO skipwhite
syn match btwBigO "\<O[ \t]*([^)]*)" contained

syn match btwEscape "\\." contained
syn region btwString start=+"+ skip=+\\.+ end=+"+ end=+$+ oneline contains=btwEscape

syn match btwComment "//.*$"

hi def link btwDirective Keyword
hi def link btwConditional Conditional
hi def link btwRepeat Repeat
hi def link btwReturn Statement
hi def link btwStorage Type
hi def link btwOther Statement
hi def link btwConsoleLog Function
hi def link btwBoolean Boolean
hi def link btwNumber Number
hi def link btwFuncName Function
hi def link btwBigO Type
hi def link btwString String
hi def link btwEscape SpecialChar
hi def link btwComment Comment

let b:current_syntax = "btw"
