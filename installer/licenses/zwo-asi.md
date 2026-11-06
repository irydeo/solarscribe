# ZWO ASI Camera SDK

- **Vendor**: ZWO Company
- **Files shipped on Windows**: `ASICamera2.dll`
- **Files shipped on Linux**: `libASICamera2.so`, `libASICamera2.so.1.41`
- **Verdict**: redistributable, bundled with the notice below
- **Reviewed**: 2026-11-06
- **Source**: <https://www.zwoastro.com/software/product-sdk>

## Evidence

The ZWO download service delivered `ASI_Camera_SDK.zip` (version 1.41). Its
Windows inner archive and its Linux/macOS inner archive both contain a
`license.txt` with the MIT text below. The notice has to travel with the
copies of the software, so this file is installed next to the binaries and is
also read by the Debian copyright and the RPM licence payload.

## Licence text

```
Copyright (c) 2015, ZWO Company
All rights reserved.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```
