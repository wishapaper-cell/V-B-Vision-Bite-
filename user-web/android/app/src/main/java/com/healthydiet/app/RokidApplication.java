package com.healthydiet.app;

import com.chaquo.python.android.PyApplication;
import com.rokid.cxr.link.CXRLink;

public final class RokidApplication extends PyApplication {
    private CXRLink cxrLink;

    @Override
    public void onCreate() {
        super.onCreate();
        cxrLink = new CXRLink(getApplicationContext());
    }

    public CXRLink getCxrLink() {
        return cxrLink;
    }
}
