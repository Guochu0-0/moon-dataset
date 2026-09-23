const kQueryArg = "q";
const kResultsArg = "show-results";

// If items don't provide a URL, then both the navigator and the onSelect
// function aren't called (and therefore, the default implementation is used)
//
// We're using this sentinel URL to signal to those handlers that this
// item is a more item (along with the type) and can be handled appropriately
const kItemTypeMoreHref = "0767FDFD-0422-4E5A-BC8A-3BE11E5BBA05";

// Capture search params and clean ?q= from URL at module load time, before
// any DOMContentLoaded handlers run. quarto-nav.js resolves all <a> hrefs
// against window.location during DOMContentLoaded — if ?q= is still present,
// every link on the page gets the query param baked into its href.
const currentUrl = new URL(window.location);
const kQuery = currentUrl.searchParams.get(kQueryArg);
if (kQuery) {
  const replacementUrl = new URL(window.location);
  replacementUrl.searchParams.delete(kQueryArg);
  window.history.replaceState({}, "", replacementUrl);
}

window.document.addEventListener("DOMContentLoaded", function (_event) {
  // Ensure that search is available on this page. If it isn't,
  // should return early and not do anything
  var searchEl = window.document.getElementById("quarto-search");
  if (!searchEl) return;

  const { autocomplete } = window["@algolia/autocomplete-js"];

  let quartoSearchOptions = {};
  let language = {};
  const searchOptionEl = window.document.getElementById(
    "quarto-search-options"
  );
  if (searchOptionEl) {
    const jsonStr = searchOptionEl.textContent;
    quartoSearchOptions = JSON.parse(jsonStr);
    language = quartoSearchOptions.language;
  }

  // note the search mode
  if (quartoSearchOptions.type === "overlay") {
    searchEl.classList.add("type-overlay");
  } else {
    searchEl.classList.add("type-textbox");
  }

  // Used to determine highlighting behavior for this page
  // A `q` query param is expected when the user follows a search
  // to this page
  const query = kQuery;
  const showSearchResults = currentUrl.searchParams.get(kResultsArg);
  const mainEl = window.document.querySelector("main");

  // highlight matches on the page
  if (query && mainEl) {
    highlight(query, mainEl);

    // Activate tabs on pageshow — after tabsets.js restores localStorage state.
    // tabsets.js registers its pageshow handler during module execution (before
    // DOMContentLoaded). By registering ours during DOMContentLoaded, listener
    // ordering guarantees we run after tabsets.js — so search activation wins.
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) {
        for (const mark of mainEl.querySelectorAll("mark")) {
          openAllTabsetsContainingEl(mark);
        }
        // Only scroll to first match when there's no hash fragment.
        // With a hash, the browser already scrolled to the target section.
        if (!currentUrl.hash) {
          requestAnimationFrame(() => scrollToFirstVisibleMatch(mainEl));
        }
      }
    }, { once: true });
  }

  // function to clear highlighting on the page when the search query changes
  // (e.g. if the user edits the query or clears it)
  let highlighting = true;
  const resetHighlighting = (searchTerm) => {
    if (mainEl && highlighting && query && searchTerm !== query) {
      clearHighlight(query, mainEl);
      highlighting = false;
    }
  };

  // Responsively switch to overlay mode if the search is present on the navbar
  // Note that switching the sidebar to overlay mode requires more coordinate (not just
  // the media query since we generate different HTML for sidebar overlays than we do
  // for sidebar input UI)
  const detachedMediaQuery =
    quartoSearchOptions.type === "overlay" ? "all" : "(max-width: 991px)";

  // If configured, include the analytics client to send insights
  const plugins = configurePlugins(quartoSearchOptions);

  let lastState = null;
  const { setIsOpen, setQuery, setCollections } = autocomplete({
    container: searchEl,
    detachedMediaQuery: detachedMediaQuery,
    defaultActiveItemId: 0,
    panelContainer: "#quarto-search-results",
    panelPlacement: quartoSearchOptions["panel-placement"],
    debug: false,
    openOnFocus: true,
    plugins,
    classNames: {
      form: "d-flex",
    },
    placeholder: language["search-text-placeholder"],
    translations: {
      clearButtonTitle: language["search-clear-button-title"],
      detachedCancelButtonText: language["search-detached-cancel-button-title"],
      submitButtonTitle: language["search-submit-button-title"],
    },
    initialState: {
      query,
    },
    getItemUrl({ item }) {
      return item.href;
    },
    onStateChange({ state }) {
      // If this is a file URL, note that

      // Perhaps reset highlighting
      resetHighlighting(state.query);

      // If the panel just opened, ensure the panel is positioned properly
      if (state.isOpen) {
        if (lastState && !lastState.isOpen) {
          setTimeout(() => {
            positionPanel(quartoSearchOptions["panel-placement"]);
          }, 150);
        }
      }

      // Perhaps show the copy link
      showCopyLink(state.query, quartoSearchOptions);

      lastState = state;
    },
    reshape({ sources, state }) {
      return sources.map((source) => {
        try {
          const items = source.getItems();

          // Validate the items
          validateItems(items);

          // group the items by document
          const groupedItems = new Map();
          items.forEach((item) => {
            const hrefParts = item.href.split("#");
            const baseHref = hrefParts[0];
            const isDocumentItem = hrefParts.length === 1;

            const items = groupedItems.get(baseHref);
            if (!items) {
              groupedItems.set(baseHref, [item]);
            } else {
              // If the href for this item matches the document
              // exactly, place this item first as it is the item that represents
              // the document itself
              if (isDocumentItem) {
                items.unshift(item);
              } else {
                items.push(item);
              }
              groupedItems.set(baseHref, items);
            }
          });

          const reshapedItems = [];
          let count = 1;
          for (const [_key, value] of groupedItems) {
            const firstItem = value[0];
            reshapedItems.push({
              ...firstItem,
              type: kItemTypeDoc,
            });

            const collapseMatches = quartoSearchOptions["collapse-after"];
            const collapseCount =
              typeof collapseMatches === "number" ? collapseMatches : 1;

            if (value.length > 1) {
              const target = `search-more-${count}`;
              const isExpanded =
                state.context.expanded &&
                state.context.expanded.includes(target);

              const remainingCount = value.length - collapseCount;

              for (let i = 1; i < value.length; i++) {
                if (collapseMatches && i === collapseCount) {
                  reshapedItems.push({
                    target,
                    title: isExpanded
                      ? language["search-hide-matches-text"]
                      : remainingCount === 1
                        ? `${remainingCount} ${language["search-more-match-text"]}`
                        : `${remainingCount} ${language["search-more-matches-text"]}`,
                    type: kItemTypeMore,
                    href: kItemTypeMoreHref,
                  });
                }

                if (isExpanded || !collapseMatches || i < collapseCount) {
                  reshapedItems.push({
                    ...value[i],
                    type: kItemTypeItem,
                    target,
                  });
                }
              }
            }
            count += 1;
          }

          return {
            ...source,
            getItems() {
              return reshapedItems;
            },
          };
        } catch (error) {
          // Some form of error occurred
          return {
            ...source,
            getItems() {
              return [
                {
                  title: error.name || "An Error Occurred While Searching",
                  text:
                    error.message ||
                    "An unknown error occurred while attempting to perform the requested search.",
                  type: kItemTypeError,
                },
              ];
            },
          };
        }
      });
    },
    navigator: {
      navigate({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          window.location.assign(itemUrl);
        }
      },
      navigateNewTab({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          const windowReference = window.open(itemUrl, "_blank", "noopener");
          if (windowReference) {
            windowReference.focus();
          }
        }
      },
      navigateNewWindow({ itemUrl }) {
        if (itemUrl !== offsetURL(kItemTypeMoreHref)) {
          window.open(itemUrl, "_blank", "noopener");
        }
      },
    },
    getSources({ state, setContext, setActiveItemId, refresh }) {
      return [
        {
          sourceId: "documents",
          getItemUrl({ item }) {
            if (item.href) {
              return offsetURL(item.href);
            } else {
              return undefined;
            }
          },
          onSelect({
            item,
            state,
            setContext,
            setIsOpen,
            setActiveItemId,
            refresh,
          }) {
            if (item.type === kItemTypeMore) {
              toggleExpanded(item, state, setContext, setActiveItemId, refresh);

              // Toggle more
              setIsOpen(true);
            }
          },
          getItems({ query }) {
            if (query === null || query === "") {
              return [];
            }

            const limit = quartoSearchOptions.limit;
            if (quartoSearchOptions.algolia) {
              return algoliaSearch(query, limit, quartoSearchOptions.algolia);
            } else {
              // Fuse search options
              const fuseSearchOptions = {
                isCaseSensitive: false,
                shouldSort: true,
                minMatchCharLength: 2,
                limit: limit,
              };

              return readSearchData().then(function (fuse) {
                return fuseSearch(query, fuse, fuseSearchOptions);
              });
            }
          },
          templates: {
            noResults({ createElement }) {
              const hasQuery = lastState.query;

              return createElement(
                "div",
                {
                  class: `quarto-search-no-results${hasQuery ? "" : " no-query"
                    }`,
                },
                language["search-no-results-text"]
              );
            },
            header({ items, createElement }) {
              // count the documents
              const count = items.filter((item) => {
                return item.type === kItemTypeDoc;
              }).length;

              if (count > 0) {
                return createElement(
                  "div",
                  { class: "search-result-header" },
                  `${count} ${language["search-matching-documents-text"]}`
                );
              } else {
                return createElement(
                  "div",
                  { class: "search-result-header-no-results" },
                  ``
                );
              }
            },
            footer({ _items, createElement }) {
              if (
                quartoSearchOptions.algolia &&
                quartoSearchOptions.algolia["show-logo"]
              ) {
                const libDir = quartoSearchOptions.algolia["libDir"];
                const logo = createElement("img", {
                  src: offsetURL(
                    `${libDir}/quarto-search/search-by-algolia.svg`
                  ),
                  class: "algolia-search-logo",
                });
                return createElement(
                  "a",
                  { href: "http://www.algolia.com/" },
                  logo
                );
              }
            },

            item({ item, createElement }) {
              if (item.text && item.href && !item.href.includes('?q=')) {
                const [main, hash] = item.href.split('#')
                const hashAppend = hash ? '#' + hash : ''
                item.href = main + '?q=' + encodeURIComponent(state.query) + hashAppend
              }

              return renderItem(
                item,
                createElement,
                state,
                setActiveItemId,
                setContext,
                refresh,
                quartoSearchOptions
              );
            },
          },
        },
      ];
    },
  });

  window.quartoOpenSearch = () => {
    setIsOpen(false);
    setIsOpen(true);
    focusSearchInput();
  };

  document.addEventListener("keyup", (event) => {
    const { key } = event;
    const kbds = quartoSearchOptions["keyboard-shortcut"];
    const focusedEl = document.activeElement;

    const isFormElFocused = [
      "input",
      "select",
      "textarea",
      "button",
      "option",
    ].find((tag) => {
      return focusedEl.tagName.toLowerCase() === tag;
    });

    if (
      kbds &&
      kbds.includes(key) &&
      !isFormElFocused &&
      !document.activeElement.isContentEditable
    ) {
      event.preventDefault();
      window.quartoOpenSearch();
    }
  });

  // Remove the labeleledby attribute since it is pointing
  // to a non-existent label
  if (quartoSearchOptions.type === "overlay") {
    const inputEl = window.document.querySelector(
      "#quarto-search .aa-Autocomplete"
    );
    if (inputEl) {
      inputEl.removeAttribute("aria-labelledby");
    }
  }

  function throttle(func, wait) {
    let waiting = false;
    return function () {
      if (!waiting) {
        func.apply(this, arguments);
        waiting = true;
        setTimeout(function () {
          waiting = false;
        }, wait);
      }
    };
  }

  // If the main document scrolls dismiss the search results
  // (otherwise, since they're floating in the document they can scroll with the document)
  window.document.body.onscroll = throttle(() => {
    // Only do this if we're not detached
    // Bug #7117
    // This will happen when the keyboard is shown on ios (resulting in a scroll)
    // which then closed the search UI
    if (!window.matchMedia(detachedMediaQuery).matches) {
      setIsOpen(false);
    }
  }, 50);

  if (showSearchResults) {
    setIsOpen(true);
    focusSearchInput();
  }
});

function configurePlugins(quartoSearchOptions) {
  const autocompletePlugins = [];
  const algoliaOptions = quartoSearchOptions.algolia;
  if (
    algoliaOptions &&
    algoliaOptions["analytics-events"] &&
    algoliaOptions["search-only-api-key"] &&
    algoliaOptions["application-id"]
  ) {
    const apiKey = algoliaOptions["search-only-api-key"];
    const appId = algoliaOptions["application-id"];

    // Aloglia insights may not be loaded because they require cookie consent
    // Use deferred loading so events will start being recorded when/if consent
    // is granted.
    const algoliaInsightsDeferredPlugin = deferredLoadPlugin(() => {
      if (
        window.aa &&
        window["@algolia/autocomplete-plugin-algolia-insights"]
      ) {
        // Check if cookie consent is enabled from search options
        const cookieConsentEnabled = algoliaOptions["cookie-consent-enabled"] || false;

        // Generate random session token only when cookies are disabled
        const userToken = cookieConsentEnabled ? undefined : Array.from(Array(20), () =>
          Math.floor(Math.random() * 36).toString(36)
        ).join("");

        window.aa("init", {
          appId,
          apiKey,
          useCookie: cookieConsentEnabled,
          userToken: userToken,
        });

        const { createAlgoliaInsightsPlugin } =
          window["@algolia/autocomplete-plugin-algolia-insights"];
        // Register the insights client
        const algoliaInsightsPlugin = createAlgoliaInsightsPlugin({
          insightsClient: window.aa,
          onItemsChange({ insights, insightsEvents }) {
            const events = insightsEvents.flatMap((event) => {
              // This API limits the number of items per event to 20
              const chunkSize = 20;
              const itemChunks = [];
              const eventItems = event.items;
              for (let i = 0; i < eventItems.length; i += chunkSize) {
                itemChunks.push(eventItems.slice(i, i + chunkSize));
              }
              // Split the items into multiple events that can be sent
              const events = itemChunks.map((items) => {
                return {
                  ...event,
                  items,
                };
              });
              return events;
            });

            for (const event of events) {
              insights.viewedObjectIDs(event);
            }
          },
        });
        return algoliaInsightsPlugin;
      }
    });

    // Add the plugin
    autocompletePlugins.push(algoliaInsightsDeferredPlugin);
    return autocompletePlugins;
  }
}

// For plugins that may not load immediately, create a wrapper
// plugin and forward events and plugin data once the plugin
// is initialized. This is useful for cases like cookie consent
// which may prevent the analytics insights event plugin from initializing
// immediately.
function deferredLoadPlugin(createPlugin) {
  let plugin = undefined;
  let subscribeObj = undefined;
  const wrappedPlugin = () => {
    if (!plugin && subscribeObj) {
      plugin = createPlugin();
      if (plugin && plugin.subscribe) {
        plugin.subscribe(subscribeObj);
      }
    }
    return plugin;
  };

  return {
    subscribe: (obj) => {
      subscribeObj = obj;
    },
    onStateChange: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onStateChange) {
        plugin.onStateChange(obj);
      }
    },
    onSubmit: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onSubmit) {
        plugin.onSubmit(obj);
      }
    },
    onReset: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.onReset) {
        plugin.onReset(obj);
      }
    },
    getSources: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.getSources) {
        return plugin.getSources(obj);
      } else {
        return Promise.resolve([]);
      }
    },
    data: (obj) => {
      const plugin = wrappedPlugin();
      if (plugin && plugin.data) {
        plugin.data(obj);
      }
    },
  };
}

function validateItems(items) {
  // Validate the first item
  if (items.length > 0) {
    const item = items[0];
    const missingFields = [];
    if (item.href == undefined) {
      missingFields.push("href");
    }
    if (!item.title == undefined) {
      missingFields.push("title");
    }
    if (!item.text == undefined) {
      missingFields.push("text");
    }

    if (missingFields.length === 1) {
      throw {
        name: `Error: Search index is missing the <code>${missingFields[0]}</code> field.`,
        message: `The items being returned for this search do not include all the required fields. Please ensure that your index items include the <code>${missingFields[0]}</code> field or use <code>index-fields</code> in your <code>_quarto.yml</code> file to specify the field names.`,
      };
    } else if (missingFields.length > 1) {
      const missingFieldList = missingFields
        .map((field) => {
          return `<code>${field}</code>`;
        })
        .join(", ");

      throw {
        name: `Error: Search index is missing the following fields: ${missingFieldList}.`,
        message: `The items being returned for this search do not include all the required fields. Please ensure that your index items includes the following fields: ${missingFieldList}, or use <code>index-fields</code> in your <code>_quarto.yml</code> file to specify the field names.`,
      };
    }
  }
}

let lastQuery = null;
function showCopyLink(query, options) {
  const language = options.language;
  lastQuery = query;
  // Insert share icon
  const inputSuffixEl = window.document.body.querySelector(
    ".aa-Form .aa-InputWrapperSuffix"
  );

  if (inputSuffixEl) {
    let copyButtonEl = window.document.body.querySelector(
      ".aa-Form .aa-InputWrapperSuffix .aa-CopyButton"
    );

    if (copyButtonEl === null) {
      copyButtonEl = window.document.createElement("button");
      copyButtonEl.setAttribute("class", "aa-CopyButton");
      copyButtonEl.setAttribute("type", "button");
      copyButtonEl.setAttribute("title", language["search-copy-link-title"]);
      copyButtonEl.onmousedown = (e) => {
        e.preventDefault();
        e.stopPropagation();
      };

      const linkIcon = "bi-clipboard";
      const checkIcon = "bi-check2";

      const shareIconEl = window.document.createElement("i");
      shareIconEl.setAttribute("class", `bi ${linkIcon}`);
      copyButtonEl.appendChild(shareIconEl);
      inputSuffixEl.prepend(copyButtonEl);

      const clipboard = new window.ClipboardJS(".aa-CopyButton", {
        text: function (_trigger) {
          const copyUrl = new URL(window.location);
          copyUrl.searchParams.set(kQueryArg, lastQuery);
          copyUrl.searchParams.set(kResultsArg, "1");
          return copyUrl.toString();
        },
      });
      clipboard.on("success", function (e) {
        // Focus the input

        // button target
        const button = e.trigger;
        const icon = button.querySelector("i.bi");

        // flash "checked"
        icon.classList.add(checkIcon);
        icon.classList.remove(linkIcon);
        setTimeout(function () {
          icon.classList.remove(checkIcon);
          icon.classList.add(linkIcon);
        }, 1000);
      });
    }

    // If there is a query, show the link icon
    if (copyButtonEl) {
      if (lastQuery && options["copy-button"]) {
        copyButtonEl.style.display = "flex";
      } else {
        copyButtonEl.style.display = "none";
      }
    }
  }
}

/* Search Index Handling */
// create the index
var fuseIndex = undefined;
var shownWarning = false;

// fuse index options
const kFuseIndexOptions = {
  keys: [
    { name: "title", weight: 20 },
    { name: "section", weight: 20 },
    { name: "text", weight: 10 },
  ],
  ignoreLocation: true,
  threshold: 0.1,
};

async function readSearchData() {
  // Initialize the search index on demand
  if (fuseIndex === undefined) {
    if (false /* moondata: 索引已内嵌，file:// 下同样可用 */) {
      window.alert(
        "Search requires JavaScript features disabled when running in file://... URLs. In order to use search, please run this document in a web server."
      );
      shownWarning = true;
      return;
    }
    const fuse = new window.Fuse([], kFuseIndexOptions);

    // fetch the main search.json
    const response = __moondataOfflineSearchResponse();
    if (response.status == 200) {
      return response.json().then(function (searchDocs) {
        searchDocs.forEach(function (searchDoc) {
          fuse.add(searchDoc);
        });
        fuseIndex = fuse;
        return fuseIndex;
      });
    } else {
      return Promise.reject(
        new Error(
          "Unexpected status from search index request: " + response.status
        )
      );
    }
  }

  return fuseIndex;
}

function inputElement() {
  return window.document.body.querySelector(".aa-Form .aa-Input");
}

function focusSearchInput() {
  setTimeout(() => {
    const inputEl = inputElement();
    if (inputEl) {
      inputEl.focus();
    }
  }, 50);
}

/* Panels */
const kItemTypeDoc = "document";
const kItemTypeMore = "document-more";
const kItemTypeItem = "document-item";
const kItemTypeError = "error";

function renderItem(
  item,
  createElement,
  state,
  setActiveItemId,
  setContext,
  refresh,
  quartoSearchOptions
) {
  switch (item.type) {
    case kItemTypeDoc:
      return createDocumentCard(
        createElement,
        "file-richtext",
        item.title,
        item.section,
        item.text,
        item.href,
        item.crumbs,
        quartoSearchOptions
      );
    case kItemTypeMore:
      return createMoreCard(
        createElement,
        item,
        state,
        setActiveItemId,
        setContext,
        refresh
      );
    case kItemTypeItem:
      return createSectionCard(
        createElement,
        item.section,
        item.text,
        item.href
      );
    case kItemTypeError:
      return createErrorCard(createElement, item.title, item.text);
    default:
      return undefined;
  }
}

function createDocumentCard(
  createElement,
  icon,
  title,
  section,
  text,
  href,
  crumbs,
  quartoSearchOptions
) {
  const iconEl = createElement("i", {
    class: `bi bi-${icon} search-result-icon`,
  });
  const titleEl = createElement("p", { class: "search-result-title" }, title);
  const titleContents = [iconEl, titleEl];
  const showParent = quartoSearchOptions["show-item-context"];
  if (crumbs && showParent) {
    let crumbsOut = undefined;
    const crumbClz = ["search-result-crumbs"];
    if (showParent === "root") {
      crumbsOut = crumbs.length > 1 ? crumbs[0] : undefined;
    } else if (showParent === "parent") {
      crumbsOut = crumbs.length > 1 ? crumbs[crumbs.length - 2] : undefined;
    } else {
      crumbsOut = crumbs.length > 1 ? crumbs.join(" > ") : undefined;
      crumbClz.push("search-result-crumbs-wrap");
    }

    const crumbEl = createElement(
      "p",
      { class: crumbClz.join(" ") },
      crumbsOut
    );
    titleContents.push(crumbEl);
  }

  const titleContainerEl = createElement(
    "div",
    { class: "search-result-title-container" },
    titleContents
  );

  const textEls = [];
  if (section) {
    const sectionEl = createElement(
      "p",
      { class: "search-result-section" },
      section
    );
    textEls.push(sectionEl);
  }
  const descEl = createElement("p", {
    class: "search-result-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });
  textEls.push(descEl);

  const textContainerEl = createElement(
    "div",
    { class: "search-result-text-container" },
    textEls
  );

  const containerEl = createElement(
    "div",
    {
      class: "search-result-container",
    },
    [titleContainerEl, textContainerEl]
  );

  const linkEl = createElement(
    "a",
    {
      href: offsetURL(href),
      class: "search-result-link",
    },
    containerEl
  );

  const classes = ["search-result-doc", "search-item"];
  if (!section) {
    classes.push("document-selectable");
  }

  return createElement(
    "div",
    {
      class: classes.join(" "),
    },
    linkEl
  );
}

function createMoreCard(
  createElement,
  item,
  state,
  setActiveItemId,
  setContext,
  refresh
) {
  const moreCardEl = createElement(
    "div",
    {
      class: "search-result-more search-item",
      onClick: (e) => {
        // Handle expanding the sections by adding the expanded
        // section to the list of expanded sections
        toggleExpanded(item, state, setContext, setActiveItemId, refresh);
        e.stopPropagation();
      },
    },
    item.title
  );

  return moreCardEl;
}

function toggleExpanded(item, state, setContext, setActiveItemId, refresh) {
  const expanded = state.context.expanded || [];
  if (expanded.includes(item.target)) {
    setContext({
      expanded: expanded.filter((target) => target !== item.target),
    });
  } else {
    setContext({ expanded: [...expanded, item.target] });
  }

  refresh();
  setActiveItemId(item.__autocomplete_id);
}

function createSectionCard(createElement, section, text, href) {
  const sectionEl = createSection(createElement, section, text, href);
  return createElement(
    "div",
    {
      class: "search-result-doc-section search-item",
    },
    sectionEl
  );
}

function createSection(createElement, title, text, href) {
  const descEl = createElement("p", {
    class: "search-result-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });

  const titleEl = createElement("p", { class: "search-result-section" }, title);
  const linkEl = createElement(
    "a",
    {
      href: offsetURL(href),
      class: "search-result-link",
    },
    [titleEl, descEl]
  );
  return linkEl;
}

function createErrorCard(createElement, title, text) {
  const descEl = createElement("p", {
    class: "search-error-text",
    dangerouslySetInnerHTML: {
      __html: text,
    },
  });

  const titleEl = createElement("p", {
    class: "search-error-title",
    dangerouslySetInnerHTML: {
      __html: `<i class="bi bi-exclamation-circle search-error-icon"></i> ${title}`,
    },
  });
  const errorEl = createElement("div", { class: "search-error" }, [
    titleEl,
    descEl,
  ]);
  return errorEl;
}

function positionPanel(pos) {
  const panelEl = window.document.querySelector(
    "#quarto-search-results .aa-Panel"
  );
  const inputEl = window.document.querySelector(
    "#quarto-search .aa-Autocomplete"
  );

  if (panelEl && inputEl) {
    panelEl.style.top = `${Math.round(panelEl.offsetTop)}px`;
    if (pos === "start") {
      panelEl.style.left = `${Math.round(inputEl.left)}px`;
    } else {
      panelEl.style.right = `${Math.round(inputEl.offsetRight)}px`;
    }
  }
}

/* Highlighting */
// highlighting functions
function highlightMatch(query, text) {
  if (text) {
    const start = text.toLowerCase().indexOf(query.toLowerCase());
    if (start !== -1) {
      const startMark = "<mark class='search-match'>";
      const endMark = "</mark>";

      const end = start + query.length;
      text =
        text.slice(0, start) +
        startMark +
        text.slice(start, end) +
        endMark +
        text.slice(end);
      const startInfo = clipStart(text, start);
      const endInfo = clipEnd(
        text,
        startInfo.position + startMark.length + endMark.length
      );
      text =
        startInfo.prefix +
        text.slice(startInfo.position, endInfo.position) +
        endInfo.suffix;

      return text;
    } else {
      return text;
    }
  } else {
    return text;
  }
}

function clipStart(text, pos) {
  const clipStart = pos - 50;
  if (clipStart < 0) {
    // This will just return the start of the string
    return {
      position: 0,
      prefix: "",
    };
  } else {
    // We're clipping before the start of the string, walk backwards to the first space.
    const spacePos = findSpace(text, pos, -1);
    return {
      position: spacePos.position,
      prefix: "",
    };
  }
}

function clipEnd(text, pos) {
  const clipEnd = pos + 200;
  if (clipEnd > text.length) {
    return {
      position: text.length,
      suffix: "",
    };
  } else {
    const spacePos = findSpace(text, clipEnd, 1);
    return {
      position: spacePos.position,
      suffix: spacePos.clipped ? "…" : "",
    };
  }
}

function findSpace(text, start, step) {
  let stepPos = start;
  while (stepPos > -1 && stepPos < text.length) {
    const char = text[stepPos];
    if (char === " " || char === "," || char === ":") {
      return {
        position: step === 1 ? stepPos : stepPos - step,
        clipped: stepPos > 1 && stepPos < text.length,
      };
    }
    stepPos = stepPos + step;
  }

  return {
    position: stepPos - step,
    clipped: false,
  };
}

// removes highlighting as implemented by the mark tag
function clearHighlight(searchterm, el) {
  const childNodes = el.childNodes;
  for (let i = childNodes.length - 1; i >= 0; i--) {
    const node = childNodes[i];
    if (node.nodeType === Node.ELEMENT_NODE) {
      if (
        node.tagName === "MARK" &&
        node.innerText.toLowerCase() === searchterm.toLowerCase()
      ) {
        el.replaceChild(document.createTextNode(node.innerText), node);
      } else {
        clearHighlight(searchterm, node);
      }
    }
  }
}

/** Get all html nodes under the given `root` that don't have children. */
function getLeafNodes(root) {
  let leaves = [];

  function traverse(node) {
    if (node.childNodes.length === 0) {
      leaves.push(node);
    } else {
      node.childNodes.forEach(traverse);
    }
  }

  traverse(root);
  return leaves;
}
/** create and return `<mark>${txt}</mark>` */
const markEl = txt => {
  const el = document.createElement("mark");
  el.appendChild(document.createTextNode(txt));
  return el
}
/** get all ancestors of an element matching the given css selector */
const matchAncestors = (el, selector) => {
  let ancestors = [];
  while (el) {
    if (el.matches?.(selector)) ancestors.push(el);
    el = el.parentNode;
  }
  return ancestors;
};

const isWhitespace = s => s.trim().length === 0
// =================
// MATCHING CODE
// =================
const initMatch = () => ({
  i: 0,
  lohisByNode: new Map()
})
/** 
 * keeps track of the start (lo) and end (hi) index of the match per node (leaf)
 * note: mutates the contents of `matchContext`
 */
const advanceMatch = (leaf, leafi, matchContext) => {
  matchContext.i++

  const curLoHi = matchContext.lohisByNode.get(leaf)

  matchContext.lohisByNode.set(leaf, { lo: curLoHi?.lo ?? leafi, hi: leafi })
}
/**
 * Finds all non-overlapping matches for a search string in the document. 
 * The search string may be split between multiple consecutive leaf nodes.
 * 
 * Whitespace in the search string must be present in the document to match, but
 * there may be addititional whitespace in the document that is ignored.
 * 
 * e.g. searching for `dogs rock` would match `dogs  \n <span> rock</span>`,
 * and would contribute the match 
 * `{ i:9, els: new Map([[textNode, {lo:0, hi:8}],[spanNode,{lo:0,hi:5}]]) }`
 * 
 * @returns {Map<HTMLElement,{lo:number,hi:number}>[]}
 */
function searchMatches(inSearch, el) {
  // searchText has all sequences of whitespace replaced by a single space
  const searchText = inSearch.toLowerCase().replace(/\s+/g, ' ')
  const leafNodes = getLeafNodes(el)

  /** @type {Map<HTMLElement,{lo:number,hi:number}>[]} */
  const matches = []
  /** @type {{i:number; els:Map<HTMLElement,{lo:number,hi:number}>}[]} */
  let curMatchContext = initMatch()

  for (const leaf of leafNodes) {
    const leafStr = leaf.textContent.toLowerCase()
    // for each character in this leaf's text:
    for (let leafi = 0; leafi < leafStr.length; leafi++) {

      if (isWhitespace(leafStr[leafi])) {
        // if there is at least one whitespace in the document
        // we advance over a search text whitespace.
        if (isWhitespace(searchText[curMatchContext.i])) advanceMatch(leaf, leafi, curMatchContext)
        // all sequences of whitespace are otherwise ignored.
      } else {
        if (searchText[curMatchContext.i] === leafStr[leafi]) {
          advanceMatch(leaf, leafi, curMatchContext)
        } else {
          curMatchContext = initMatch()
          // if current character in the document did not match at i in the search text,
          // reset the search and see if that character matches at 0 in the search text.
          if (searchText[curMatchContext.i] === leafStr[leafi]) advanceMatch(leaf, leafi, curMatchContext)
        }
      }

      const isMatchComplete = curMatchContext.i === searchText.length
      if (isMatchComplete) {
        matches.push(curMatchContext.lohisByNode)
        curMatchContext = initMatch()
      }
    }
  }

  return matches
}

/** 
 * e.g. `markMatches(myTextNode, [[0,5],[12,15]])` would wrap the
 * character sequences in myTextNode from 0-5 and 12-15 in marks.
 * Its important to mark all sequences in a text node at once
 * because this function replaces the entire text node; so any
 * other references to that text node will no longer be in the DOM.
 */
function markMatches(node, lohis) {
  const text = node.nodeValue

  const markFragment = document.createDocumentFragment();

  let prevHi = 0
  for (const [lo, hi] of lohis) {
    markFragment.append(
      document.createTextNode(text.slice(prevHi, lo)),
      markEl(text.slice(lo, hi + 1))
    )
    prevHi = hi + 1
  }
  markFragment.append(
    document.createTextNode(text.slice(prevHi, text.length))
  )

  const parent = node.parentElement
  parent?.replaceChild(markFragment, node)
  return parent
}

// Activate ancestor tabs so a search match inside an inactive pane becomes visible.
// When multiple panes in the same tabset contain matches, avoid switching away from
// the currently active pane — the user already sees a match there.
function openAllTabsetsContainingEl(el) {
  for (const pane of matchAncestors(el, '.tab-pane')) {
    const tabContent = pane.closest('.tab-content');
    if (!tabContent) continue;
    const activePane = tabContent.querySelector(':scope > .tab-pane.active');
    if (activePane?.querySelector('mark')) continue;
    const tabButton = document.querySelector(`[data-bs-target="#${pane.id}"]`);
    if (tabButton) new bootstrap.Tab(tabButton).show();
  }
}

function scrollToFirstVisibleMatch(mainEl) {
  for (const mark of mainEl.querySelectorAll("mark")) {
    const isMarkVisible = matchAncestors(mark, '.tab-pane').every(markTabPane =>
      markTabPane.classList.contains("active")
    )
    if (isMarkVisible) {
      mark.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
  }
}

/**
 * e.g.
 * ```js
 * const m = new Map()
 *
 * arrayMapPush(m, 'dog', 'Max')
 * console.log(m) // Map { dog->['Max'] }
 * 
 * arrayMapPush(m, 'dog', 'Samba')
 * arrayMapPush(m, 'cat', 'Scruffle')
 * console.log(m) // Map { dog->['Max', 'Samba'], cat->['Scruffle'] }
 * ```
 */
const arrayMapPush = (map, key, item) => {
  if (!map.has(key)) map.set(key, [])
  map.set(key, [...map.get(key), item])
}

// copy&paste any string from a quarto page and
// this should find that string in the page and highlight it.
// exception: text that starts outside/inside a tabset and ends
// inside/outside that tabset. 
function highlight(searchStr, el) {
  const matches = searchMatches(searchStr, el);

  const matchesGroupedByNode = new Map()
  for (const match of matches) {
    for (const [mel, { lo, hi }] of match) {
      arrayMapPush(matchesGroupedByNode, mel, [lo, hi])
    }
  }

  for (const [node, lohis] of matchesGroupedByNode) {
    markMatches(node, lohis)
  }
}

/* Link Handling */
// get the offset from this page for a given site root relative url
function offsetURL(url) {
  var offset = getMeta("quarto:offset");
  return offset ? offset + url : url;
}

// read a meta tag value
function getMeta(metaName) {
  var metas = window.document.getElementsByTagName("meta");
  for (let i = 0; i < metas.length; i++) {
    if (metas[i].getAttribute("name") === metaName) {
      return metas[i].getAttribute("content");
    }
  }
  return "";
}

function algoliaSearch(query, limit, algoliaOptions) {
  const { getAlgoliaResults } = window["@algolia/autocomplete-preset-algolia"];

  const applicationId = algoliaOptions["application-id"];
  const searchOnlyApiKey = algoliaOptions["search-only-api-key"];
  const indexName = algoliaOptions["index-name"];
  const indexFields = algoliaOptions["index-fields"];
  const searchClient = window.algoliasearch(applicationId, searchOnlyApiKey);
  const searchParams = algoliaOptions["params"];
  const searchAnalytics = !!algoliaOptions["analytics-events"];

  return getAlgoliaResults({
    searchClient,
    queries: [
      {
        indexName: indexName,
        query,
        params: {
          hitsPerPage: limit,
          clickAnalytics: searchAnalytics,
          ...searchParams,
        },
      },
    ],
    transformResponse: (response) => {
      if (!indexFields) {
        return response.hits.map((hit) => {
          return hit.map((item) => {
            return {
              ...item,
              text: highlightMatch(query, item.text),
            };
          });
        });
      } else {
        const remappedHits = response.hits.map((hit) => {
          return hit.map((item) => {
            const newItem = { ...item };
            ["href", "section", "title", "text", "crumbs"].forEach(
              (keyName) => {
                const mappedName = indexFields[keyName];
                if (
                  mappedName &&
                  item[mappedName] !== undefined &&
                  mappedName !== keyName
                ) {
                  newItem[keyName] = item[mappedName];
                  delete newItem[mappedName];
                }
              }
            );
            newItem.text = highlightMatch(query, newItem.text);
            return newItem;
          });
        });
        return remappedHits;
      }
    },
  });
}

let subSearchTerm = undefined;
let subSearchFuse = undefined;
const kFuseMaxWait = 125;

async function fuseSearch(query, fuse, fuseOptions) {
  let index = fuse;
  // Fuse.js using the Bitap algorithm for text matching which runs in
  // O(nm) time (no matter the structure of the text). In our case this
  // means that long search terms mixed with large index gets very slow
  //
  // This injects a subIndex that will be used once the terms get long enough
  // Usually making this subindex is cheap since there will typically be
  // a subset of results matching the existing query
  if (subSearchFuse !== undefined && query.startsWith(subSearchTerm)) {
    // Use the existing subSearchFuse
    index = subSearchFuse;
  } else if (subSearchFuse !== undefined) {
    // The term changed, discard the existing fuse
    subSearchFuse = undefined;
    subSearchTerm = undefined;
  }

  // Search using the active fuse
  const then = performance.now();
  const resultsRaw = await index.search(query, fuseOptions);
  const now = performance.now();

  const results = resultsRaw.map((result) => {
    const addParam = (url, name, value) => {
      const anchorParts = url.split("#");
      const baseUrl = anchorParts[0];
      const sep = baseUrl.search("\\?") > 0 ? "&" : "?";
      anchorParts[0] = baseUrl + sep + name + "=" + value;
      return anchorParts.join("#");
    };

    return {
      title: result.item.title,
      section: result.item.section,
      href: addParam(result.item.href, kQueryArg, query),
      text: highlightMatch(query, result.item.text),
      crumbs: result.item.crumbs,
    };
  });

  // If we don't have a subfuse and the query is long enough, go ahead
  // and create a subfuse to use for subsequent queries
  if (
    now - then > kFuseMaxWait &&
    subSearchFuse === undefined &&
    resultsRaw.length < fuseOptions.limit
  ) {
    subSearchTerm = query;
    subSearchFuse = new window.Fuse([], kFuseIndexOptions);
    resultsRaw.forEach((rr) => {
      subSearchFuse.add(rr.item);
    });
  }
  return results;
}

/* >>> moondata:offline-search-index —— 由 moondata.docsite 生成，勿手改 */
const __moondataSearchDocuments = [{"objectID": "docs/rois/index.html", "href": "docs/rois/index.html", "title": "ROI 档案", "section": "", "text": "数据集里的 67 个 ROI 各有一页，点 ROI 编号进入。划分与数量的口径见产物文档。", "crumbs": ["首页", "主体文档", "ROI 档案"]}, {"objectID": "docs/rois/index.html#总览", "href": "docs/rois/index.html#总览", "title": "ROI 档案", "section": "总览", "text": "总览\n\n\n\nROI\n划分\npatch 对\n带真值点的\n入射角\n视向\n已知问题\n\n\n\n\nROI_001\n训练集\n40\n—\n49.75°\nLEFT\n\n\n\nROI_002\n训练集\n152\n—\n51.77°\nLEFT\n轻度的局部错位\n\n\nROI_003\n训练集\n171\n—\n49.28°\nRIGHT\n轻度的局部错位\n\n\nROI_005\n训练集\n135\n—\n50.97°\nRIGHT\n\n\n\nROI_006\n测试集\n81\n67\n49.47°\nLEFT\n\n\n\nROI_007\n测试集\n372\n286\n50.66°\nRIGHT\n\n\n\nROI_008\n训练集\n291\n—\n46.44°\nLEFT\n明显的局部错位\n\n\nROI_009\n训练集\n162\n—\n52.47°\nLEFT\n局部错位，错开的距离随位置变化\n\n\nROI_010\n训练集\n159\n—\n51.38°\nLEFT\n轻度的局部错位\n\n\nROI_011\n测试集\n92\n83\n51.41°\nLEFT\n目录里有别处遗留的控制点文件\n\n\nROI_012\n训练集\n105\n—\n54.71°\nLEFT\n\n\n\nROI_013\n训练集\n54\n—\n53.68°\nLEFT\n\n\n\nROI_015\n训练集\n98\n—\n50.05°\nLEFT\n轻度的局部错位\n\n\nROI_016\n训练集\n265\n—\n49.95°\nRIGHT\n明显的局部错位\n\n\nROI_017\n训练集\n213\n—\n47.76°\nLEFT\n与 ROI_054 的范围部分重叠\n\n\nROI_018\n训练集\n117\n—\n50.40°\nRIGHT\n\n\n\nROI_020\n测试集\n112\n91\n49.39°\nRIGHT\n\n\n\nROI_021\n训练集\n108\n—\n52.40°\nLEFT\n\n\n\nROI_023\n训练集\n175\n—\n50.70°\nRIGHT\n轻度的局部错位\n\n\nROI_024\n训练集\n239\n—\n52.39°\nLEFT\n\n\n\nROI_025\n训练集\n222\n—\n49.50°\nRIGHT\n明显的局部错位\n\n\nROI_026\n训练集\n190\n—\n46.92°\nLEFT\n轻度的局部错位\n\n\nROI_027\n训练集\n234\n—\n48.90°\nRIGHT\n轻度的局部错位；编号缺 95、98、99\n\n\nROI_030\n训练集\n74\n—\n51.04°\nLEFT\n\n\n\nROI_031\n训练集\n149\n—\n52.87°\nLEFT\n\n\n\nROI_033\n训练集\n269\n—\n51.70°\nRIGHT\n\n\n\nROI_034\n训练集\n199\n—\n53.72°\nLEFT\n一幅 CE-2 分幅的经度差了 180°\n\n\nROI_035\n验证集\n214\n172\n50.97°\nLEFT\n\n\n\nROI_037\n测试集\n159\n141\n53.04°\nLEFT\n与 ROI_060 重复（ROI_060 已删除）\n\n\nROI_038\n训练集\n64\n—\n53.26°\nLEFT\n与 ROI_071 的范围部分重叠\n\n\nROI_042\n训练集\n21\n—\n48.20°\nRIGHT\n\n\n\nROI_043\n训练集\n48\n—\n52.81°\nLEFT\n\n\n\nROI_045\n训练集\n58\n—\n51.65°\nLEFT\n\n\n\nROI_046\n训练集\n165\n—\n51.48°\nLEFT\n\n\n\nROI_047\n训练集\n31\n—\n54.92°\nLEFT\n\n\n\nROI_048\n训练集\n24\n—\n45.52°\nLEFT\n轻度的局部错位\n\n\nROI_049\n验证集\n113\n88\n52.47°\nLEFT\n\n\n\nROI_050\n训练集\n160\n—\n47.62°\nLEFT\n明显的局部错位\n\n\nROI_051\n训练集\n196\n—\n52.12°\nLEFT\n\n\n\nROI_052\n训练集\n170\n—\n48.80°\nLEFT\n明显的局部错位\n\n\nROI_053\n训练集\n93\n—\n49.57°\nLEFT\n\n\n\nROI_054\n测试集\n168\n145\n47.55°\nLEFT\n轻度的局部错位；Mini-RF 目录里有两个 SAR 文件；与 ROI_017 的范围部分重叠\n\n\nROI_055\n训练集\n214\n—\n50.53°\nRIGHT\n轻度的局部错位\n\n\nROI_056\n训练集\n296\n—\n48.59°\nLEFT\n轻度的局部错位\n\n\nROI_057\n训练集\n229\n—\n53.26°\nLEFT\nCE-2 分幅的投影参数被改错，读取时纠正\n\n\nROI_058\n训练集\n248\n—\n51.37°\nRIGHT\nCE-2 分幅的投影参数被改错，读取时纠正\n\n\nROI_059\n测试集\n146\n140\n53.67°\nLEFT\n\n\n\nROI_061\n训练集\n97\n—\n52.99°\nLEFT\n\n\n\nROI_062\n训练集\n136\n—\n53.16°\nLEFT\n\n\n\nROI_063\n训练集\n103\n—\n53.16°\nLEFT\n\n\n\nROI_064\n训练集\n111\n—\n53.18°\nLEFT\n\n\n\nROI_065\n训练集\n172\n—\n53.02°\nLEFT\n轻度的局部错位；CE-2 分幅的投影参数被改错，读取时纠正\n\n\nROI_066\n训练集\n130\n—\n52.28°\nLEFT\n\n\n\nROI_067\n训练集\n120\n—\n53.71°\nLEFT\n\n\n\nROI_068\n训练集\n107\n—\n52.55°\nLEFT\n轻度的局部错位\n\n\nROI_069\n训练集\n198\n—\n50.10°\nLEFT\n轻度的局部错位\n\n\nROI_070\n验证集\n168\n113\n52.72°\nLEFT\nCE-2 分幅的投影参数被改错，读取时纠正\n\n\nROI_071\n验证集\n40\n30\n52.57°\nLEFT\n与 ROI_038 的范围部分重叠\n\n\nROI_072\n训练集\n60\n—\n52.20°\nLEFT\n\n\n\nROI_073\n训练集\n119\n—\n52.96°\nLEFT\n对齐控制点重标过，patch 重新编号；CE-2 分幅的投影参数被改错，读取时纠正\n\n\nROI_074\n训练集\n141\n—\n52.10°\nLEFT\nROI_73 的一份作废控制点实为本 ROI 的\n\n\nROI_075\n验证集\n183\n174\n51.79°\nLEFT\n\n\n\nROI_076\n训练集\n58\n—\n53.25°\nLEFT\n\n\n\nROI_077\n训练集\n165\n—\n51.93°\nLEFT\n\n\n\nROI_078\n训练集\n167\n—\n48.46°\nLEFT\n轻度的局部错位\n\n\nROI_079\n训练集\n185\n—\n50.04°\nRIGHT\n轻度的局部错位\n\n\nROI_080\n验证集\n107\n75\n53.71°\nLEFT", "crumbs": ["首页", "主体文档", "ROI 档案"]}, {"objectID": "docs/rois/index.html#已知问题一览", "href": "docs/rois/index.html#已知问题一览", "title": "ROI 档案", "section": "已知问题一览", "text": "已知问题一览\n照实记录，不做解释；多数待作者复核。每条的出处写在档案页上。\n\n与 ROI_060 重复（ROI_060 已删除）：ROI_037\n明显的局部错位：ROI_008、ROI_016、ROI_025、ROI_050、ROI_052\n轻度的局部错位：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079\n局部错位，错开的距离随位置变化：ROI_009\n对齐控制点重标过，patch 重新编号：ROI_073\nROI_73 的一份作废控制点实为本 ROI 的：ROI_074\nCE-2 分幅的投影参数被改错，读取时纠正：ROI_057、ROI_058、ROI_065、ROI_070、ROI_073\n编号缺 95、98、99：ROI_027\n一幅 CE-2 分幅的经度差了 180°：ROI_034\nMini-RF 目录里有两个 SAR 文件：ROI_054\n目录里有别处遗留的控制点文件：ROI_011\n与 ROI_054 的范围部分重叠：ROI_017\n与 ROI_017 的范围部分重叠：ROI_054\n与 ROI_071 的范围部分重叠：ROI_038\n与 ROI_038 的范围部分重叠：ROI_071", "crumbs": ["首页", "主体文档", "ROI 档案"]}, {"objectID": "docs/rois/index.html#这些页面是怎么来的", "href": "docs/rois/index.html#这些页面是怎么来的", "title": "ROI 档案", "section": "这些页面是怎么来的", "text": "这些页面是怎么来的\n全部由 moondata pages 生成（quarto render 会先自动跑一遍），不手写任何一页：\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。\n\n缩略图要读对齐影像，所以只能接上数据盘生成（moondata thumbnails），生成后作为产物随仓库提交；其余输入都在仓库里，没插盘也能重新生成页面。", "crumbs": ["首页", "主体文档", "ROI 档案"]}, {"objectID": "docs/rois/ROI_079.html", "href": "docs/rois/ROI_079.html", "title": "ROI_079", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n185\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_079/\n\n\n对齐控制点\ndata/tie-points/ROI_79/\n\n\n元数据表中的写法\nROI_79"}, {"objectID": "docs/rois/ROI_079.html#概况", "href": "docs/rois/ROI_079.html#概况", "title": "ROI_079", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n185\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_079/\n\n\n对齐控制点\ndata/tie-points/ROI_79/\n\n\n元数据表中的写法\nROI_79"}, {"objectID": "docs/rois/ROI_079.html#mini-rf-条带", "href": "docs/rois/ROI_079.html#mini-rf-条带", "title": "ROI_079", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04652_2CD_EKU_34S056_V1\n官方\n\n\n轨道号\n4652\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-06-29T10:56:02\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.04°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n270.90°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,797 × 65,590 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n17.9 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_079.html#已知问题", "href": "docs/rois/ROI_079.html#已知问题", "title": "ROI_079", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_079.html#缩略图", "href": "docs/rois/ROI_079.html#缩略图", "title": "ROI_079", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 85.64 ~ 145.1\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.56 ~ -5.654 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_79/cropped/ce2/opt.tif、raw/ROI_79/cropped/ce2/sar.tif（4,654 × 32,793 像素），每 55 × 55 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_079.html#本页数字从哪来", "href": "docs/rois/ROI_079.html#本页数字从哪来", "title": "ROI_079", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_077.html", "href": "docs/rois/ROI_077.html", "title": "ROI_077", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n165\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_077/\n\n\n对齐控制点\ndata/tie-points/ROI_77/\n\n\n元数据表中的写法\nROI_77"}, {"objectID": "docs/rois/ROI_077.html#概况", "href": "docs/rois/ROI_077.html#概况", "title": "ROI_077", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n165\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_077/\n\n\n对齐控制点\ndata/tie-points/ROI_77/\n\n\n元数据表中的写法\nROI_77"}, {"objectID": "docs/rois/ROI_077.html#mini-rf-条带", "href": "docs/rois/ROI_077.html#mini-rf-条带", "title": "ROI_077", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02359_2CD_EKU_09N275_V1\n官方\n\n\n轨道号\n2359\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-31T08:19:26\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.93°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n89.78°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,472 × 65,937 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_077.html#缩略图", "href": "docs/rois/ROI_077.html#缩略图", "title": "ROI_077", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 69.8 ~ 110\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.45 ~ -5.816 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_77/cropped/ce2/opt.tif、raw/ROI_77/cropped/ce2/sar.tif（2,906 × 34,429 像素），每 58 × 58 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_077.html#本页数字从哪来", "href": "docs/rois/ROI_077.html#本页数字从哪来", "title": "ROI_077", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_075.html", "href": "docs/rois/ROI_075.html", "title": "ROI_075", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n183\n\n\n带评测真值点的 patch\n174 / 183（95.1%）\n\n\n评测真值点对数\n1,442\n\n\n产物目录\nProcessed_Data/Val/ROI_075/\n\n\n对齐控制点\ndata/tie-points/ROI_75/\n\n\n元数据表中的写法\nROI_75"}, {"objectID": "docs/rois/ROI_075.html#概况", "href": "docs/rois/ROI_075.html#概况", "title": "ROI_075", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n183\n\n\n带评测真值点的 patch\n174 / 183（95.1%）\n\n\n评测真值点对数\n1,442\n\n\n产物目录\nProcessed_Data/Val/ROI_075/\n\n\n对齐控制点\ndata/tie-points/ROI_75/\n\n\n元数据表中的写法\nROI_75"}, {"objectID": "docs/rois/ROI_075.html#mini-rf-条带", "href": "docs/rois/ROI_075.html#mini-rf-条带", "title": "ROI_075", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02575_2CD_EKU_39S052_V1\n官方\n\n\n轨道号\n2575\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-17T07:46:42\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.79°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n87.74°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,273 × 26,756 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n19.2 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_075.html#缩略图", "href": "docs/rois/ROI_075.html#缩略图", "title": "ROI_075", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 71.38 ~ 128.3\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.43 ~ -6.19 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_75/cropped/ce2/opt.tif、raw/ROI_75/cropped/ce2/sar.tif（4,146 × 32,837 像素），每 55 × 55 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_075.html#本页数字从哪来", "href": "docs/rois/ROI_075.html#本页数字从哪来", "title": "ROI_075", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_073.html", "href": "docs/rois/ROI_073.html", "title": "ROI_073", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n119\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_073/\n\n\n对齐控制点\ndata/tie-points/ROI_73/\n\n\n元数据表中的写法\nROI_73"}, {"objectID": "docs/rois/ROI_073.html#概况", "href": "docs/rois/ROI_073.html#概况", "title": "ROI_073", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n119\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_073/\n\n\n对齐控制点\ndata/tie-points/ROI_73/\n\n\n元数据表中的写法\nROI_73"}, {"objectID": "docs/rois/ROI_073.html#mini-rf-条带", "href": "docs/rois/ROI_073.html#mini-rf-条带", "title": "ROI_073", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01449_2CD_EKU_30N313_V1\n官方\n\n\n轨道号\n1449\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-20T19:43:13\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.96°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.80°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,949 × 33,579 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n17.8 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_073.html#已知问题", "href": "docs/rois/ROI_073.html#已知问题", "title": "ROI_073", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告对齐控制点重标过，patch 重新编号\n\n\n\n旧数据是双重错误：光学影像用了错误坐标（偏离约 205 km），而 opt_tie.* 实际标在 ROI_74 的影像上（存错了文件夹）。2026-09-11 在修正后的影像上重标了 30 对点（data/tie-points/ROI_73/cropped_2/），重切得到 119 对，原 98 对已删除，编号重新从零排起。\n窗口清单 data/windows/windows_train.json 里本 ROI 的 98 个窗口是按旧的错误控制点算的，正向复现不要求与之一致。\n出处：旧迁移记录 MIGRATION.md；data/README.md\n\n\n\n\n\n\n\n\n警告CE-2 分幅的投影参数被改错，读取时纠正\n\n\n\n本 ROI 所用的一幅 CE-2 分幅，随附投影文件的 lat_ts 抄成了相邻纬度带的值（E 带应为 35 却写成 21，I 带应为 −21 却写成 −35），像素和 geotransform 没动，整幅图因此被放到几度之外。旧代码在读取时按图幅名纠正，原文件不动；直接用通用 GIS 工具读原始瓦片会得到错误位置。\n本 ROI： 出问题的分幅：E215。\n同一条还涉及：ROI_057、ROI_058、ROI_065、ROI_070。\n出处：旧迁移记录 MIGRATION.md；旧参考文档 DATA_REFERENCE.md §2"}, {"objectID": "docs/rois/ROI_073.html#缩略图", "href": "docs/rois/ROI_073.html#缩略图", "title": "ROI_073", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 42.84 ~ 67.39\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.73 ~ -7.592 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_73/cropped/ce2/opt.tif、raw/ROI_73/cropped/ce2/sar.tif（3,261 × 27,249 像素），每 46 × 46 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_073.html#本页数字从哪来", "href": "docs/rois/ROI_073.html#本页数字从哪来", "title": "ROI_073", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_071.html", "href": "docs/rois/ROI_071.html", "title": "ROI_071", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n40\n\n\n带评测真值点的 patch\n30 / 40（75.0%）\n\n\n评测真值点对数\n241\n\n\n产物目录\nProcessed_Data/Val/ROI_071/\n\n\n对齐控制点\ndata/tie-points/ROI_71/\n\n\n元数据表中的写法\nROI_71"}, {"objectID": "docs/rois/ROI_071.html#概况", "href": "docs/rois/ROI_071.html#概况", "title": "ROI_071", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n40\n\n\n带评测真值点的 patch\n30 / 40（75.0%）\n\n\n评测真值点对数\n241\n\n\n产物目录\nProcessed_Data/Val/ROI_071/\n\n\n对齐控制点\ndata/tie-points/ROI_71/\n\n\n元数据表中的写法\nROI_71"}, {"objectID": "docs/rois/ROI_071.html#mini-rf-条带", "href": "docs/rois/ROI_071.html#mini-rf-条带", "title": "ROI_071", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01437_2CD_EKU_27N326_V1\n官方\n\n\n轨道号\n1437\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-19T21:05:02\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.57°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.71°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,904 × 30,270 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.0 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_071.html#已知问题", "href": "docs/rois/ROI_071.html#已知问题", "title": "ROI_071", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告与 ROI_038 的范围部分重叠\n\n\n\n与训练集的 ROI_038 范围重叠 17.5%，patch 级零重叠。\n出处：旧参考文档 DATA_REFERENCE.md §4"}, {"objectID": "docs/rois/ROI_071.html#缩略图", "href": "docs/rois/ROI_071.html#缩略图", "title": "ROI_071", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 39.35 ~ 68.2\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.73 ~ -5.56 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_71/cropped/ce2/opt.tif、raw/ROI_71/cropped/ce2/sar.tif（2,818 × 13,242 像素），每 23 × 23 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_071.html#本页数字从哪来", "href": "docs/rois/ROI_071.html#本页数字从哪来", "title": "ROI_071", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_069.html", "href": "docs/rois/ROI_069.html", "title": "ROI_069", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n198\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_069/\n\n\n对齐控制点\ndata/tie-points/ROI_69/\n\n\n元数据表中的写法\nROI_69"}, {"objectID": "docs/rois/ROI_069.html#概况", "href": "docs/rois/ROI_069.html#概况", "title": "ROI_069", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n198\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_069/\n\n\n对齐控制点\ndata/tie-points/ROI_69/\n\n\n元数据表中的写法\nROI_69"}, {"objectID": "docs/rois/ROI_069.html#mini-rf-条带", "href": "docs/rois/ROI_069.html#mini-rf-条带", "title": "ROI_069", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02950_2CD_EKU_16S023_V1\n官方\n\n\n轨道号\n2950\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-02-15T18:31:03\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.10°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n91.13°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,658 × 65,863 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n18.9 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_069.html#已知问题", "href": "docs/rois/ROI_069.html#已知问题", "title": "ROI_069", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_069.html#缩略图", "href": "docs/rois/ROI_069.html#缩略图", "title": "ROI_069", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 68.82 ~ 125.3\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.76 ~ -6.549 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_69/cropped/ce2/opt.tif、raw/ROI_69/cropped/ce2/sar.tif（2,939 × 49,078 像素），每 82 × 82 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_069.html#本页数字从哪来", "href": "docs/rois/ROI_069.html#本页数字从哪来", "title": "ROI_069", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_067.html", "href": "docs/rois/ROI_067.html", "title": "ROI_067", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n120\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_067/\n\n\n对齐控制点\ndata/tie-points/ROI_67/\n\n\n元数据表中的写法\nROI_67"}, {"objectID": "docs/rois/ROI_067.html#概况", "href": "docs/rois/ROI_067.html#概况", "title": "ROI_067", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n120\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_067/\n\n\n对齐控制点\ndata/tie-points/ROI_67/\n\n\n元数据表中的写法\nROI_67"}, {"objectID": "docs/rois/ROI_067.html#mini-rf-条带", "href": "docs/rois/ROI_067.html#mini-rf-条带", "title": "ROI_067", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02121_2CD_EKU_53N336_V1\n官方\n\n\n轨道号\n2121\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-12T15:03:46\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.71°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n267.42°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n6,878 × 50,289 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n51.2 m\n实测\n\n\n有效分辨率（方位向）\n18.3 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_067.html#缩略图", "href": "docs/rois/ROI_067.html#缩略图", "title": "ROI_067", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 48.55 ~ 100.4\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -16.95 ~ -5.773 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_67/cropped/ce2/opt.tif、raw/ROI_67/cropped/ce2/sar.tif（5,345 × 36,859 像素），每 62 × 62 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_067.html#本页数字从哪来", "href": "docs/rois/ROI_067.html#本页数字从哪来", "title": "ROI_067", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_065.html", "href": "docs/rois/ROI_065.html", "title": "ROI_065", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n172\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_065/\n\n\n对齐控制点\ndata/tie-points/ROI_65/\n\n\n元数据表中的写法\nROI_65"}, {"objectID": "docs/rois/ROI_065.html#概况", "href": "docs/rois/ROI_065.html#概况", "title": "ROI_065", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n172\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_065/\n\n\n对齐控制点\ndata/tie-points/ROI_65/\n\n\n元数据表中的写法\nROI_65"}, {"objectID": "docs/rois/ROI_065.html#mini-rf-条带", "href": "docs/rois/ROI_065.html#mini-rf-条带", "title": "ROI_065", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02346_2CD_EKU_32S103_V1\n官方\n\n\n轨道号\n2346\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-30T08:38:13\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.02°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n271.81°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n5,431 × 65,654 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_065.html#已知问题", "href": "docs/rois/ROI_065.html#已知问题", "title": "ROI_065", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）\n\n\n\n\n\n\n\n\n警告CE-2 分幅的投影参数被改错，读取时纠正\n\n\n\n本 ROI 所用的一幅 CE-2 分幅，随附投影文件的 lat_ts 抄成了相邻纬度带的值（E 带应为 35 却写成 21，I 带应为 −21 却写成 −35），像素和 geotransform 没动，整幅图因此被放到几度之外。旧代码在读取时按图幅名纠正，原文件不动；直接用通用 GIS 工具读原始瓦片会得到错误位置。\n本 ROI： 出问题的分幅：I236。\n同一条还涉及：ROI_057、ROI_058、ROI_070、ROI_073。\n出处：旧迁移记录 MIGRATION.md；旧参考文档 DATA_REFERENCE.md §2"}, {"objectID": "docs/rois/ROI_065.html#缩略图", "href": "docs/rois/ROI_065.html#缩略图", "title": "ROI_065", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 44.84 ~ 98.44\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.8 ~ -6.289 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_65/cropped/ce2/opt.tif、raw/ROI_65/cropped/ce2/sar.tif（5,270 × 50,254 像素），每 84 × 84 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_065.html#本页数字从哪来", "href": "docs/rois/ROI_065.html#本页数字从哪来", "title": "ROI_065", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_063.html", "href": "docs/rois/ROI_063.html", "title": "ROI_063", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n103\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_063/\n\n\n对齐控制点\ndata/tie-points/ROI_63/\n\n\n元数据表中的写法\nROI_63"}, {"objectID": "docs/rois/ROI_063.html#概况", "href": "docs/rois/ROI_063.html#概况", "title": "ROI_063", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n103\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_063/\n\n\n对齐控制点\ndata/tie-points/ROI_63/\n\n\n元数据表中的写法\nROI_63"}, {"objectID": "docs/rois/ROI_063.html#mini-rf-条带", "href": "docs/rois/ROI_063.html#mini-rf-条带", "title": "ROI_063", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01752_2CD_EKU_31N359_V1\n官方\n\n\n轨道号\n1752\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-11-13T15:13:51\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.16°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.76°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,328 × 66,606 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n19.1 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_063.html#缩略图", "href": "docs/rois/ROI_063.html#缩略图", "title": "ROI_063", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 45.06 ~ 77.95\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.67 ~ -7.114 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_63/cropped/ce2/opt.tif、raw/ROI_63/cropped/ce2/sar.tif（4,786 × 27,967 像素），每 47 × 47 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_063.html#本页数字从哪来", "href": "docs/rois/ROI_063.html#本页数字从哪来", "title": "ROI_063", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_061.html", "href": "docs/rois/ROI_061.html", "title": "ROI_061", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n97\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_061/\n\n\n对齐控制点\ndata/tie-points/ROI_61/\n\n\n元数据表中的写法\nROI_61"}, {"objectID": "docs/rois/ROI_061.html#概况", "href": "docs/rois/ROI_061.html#概况", "title": "ROI_061", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n97\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_061/\n\n\n对齐控制点\ndata/tie-points/ROI_61/\n\n\n元数据表中的写法\nROI_61"}, {"objectID": "docs/rois/ROI_061.html#mini-rf-条带", "href": "docs/rois/ROI_061.html#mini-rf-条带", "title": "ROI_061", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01779_2CD_EKU_30N332_V1\n官方\n\n\n轨道号\n1779\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-11-15T18:10:12\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.99°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n267.55°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,559 × 66,787 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.9 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_061.html#缩略图", "href": "docs/rois/ROI_061.html#缩略图", "title": "ROI_061", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 36.91 ~ 48.79\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.66 ~ -7.524 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_61/cropped/ce2/opt.tif、raw/ROI_61/cropped/ce2/sar.tif（4,424 × 32,793 像素），每 55 × 55 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_061.html#本页数字从哪来", "href": "docs/rois/ROI_061.html#本页数字从哪来", "title": "ROI_061", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_058.html", "href": "docs/rois/ROI_058.html", "title": "ROI_058", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n248\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_058/\n\n\n对齐控制点\ndata/tie-points/ROI_58/\n\n\n元数据表中的写法\nROI_58"}, {"objectID": "docs/rois/ROI_058.html#概况", "href": "docs/rois/ROI_058.html#概况", "title": "ROI_058", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n248\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_058/\n\n\n对齐控制点\ndata/tie-points/ROI_58/\n\n\n元数据表中的写法\nROI_58"}, {"objectID": "docs/rois/ROI_058.html#mini-rf-条带", "href": "docs/rois/ROI_058.html#mini-rf-条带", "title": "ROI_058", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04374_2CD_EKU_34N344_V1\n官方\n\n\n轨道号\n4374\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-06-07T14:38:37\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.37°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n268.46°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,996 × 66,124 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.3 m\n实测\n\n\n有效分辨率（方位向）\n19.2 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_058.html#已知问题", "href": "docs/rois/ROI_058.html#已知问题", "title": "ROI_058", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告CE-2 分幅的投影参数被改错，读取时纠正\n\n\n\n本 ROI 所用的一幅 CE-2 分幅，随附投影文件的 lat_ts 抄成了相邻纬度带的值（E 带应为 35 却写成 21，I 带应为 −21 却写成 −35），像素和 geotransform 没动，整幅图因此被放到几度之外。旧代码在读取时按图幅名纠正，原文件不动；直接用通用 GIS 工具读原始瓦片会得到错误位置。\n本 ROI： 出问题的分幅：E219。\n同一条还涉及：ROI_057、ROI_065、ROI_070、ROI_073。\n出处：旧迁移记录 MIGRATION.md；旧参考文档 DATA_REFERENCE.md §2"}, {"objectID": "docs/rois/ROI_058.html#缩略图", "href": "docs/rois/ROI_058.html#缩略图", "title": "ROI_058", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 38.06 ~ 51.7\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.35 ~ -6.113 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_58/cropped/ce2/opt.tif、raw/ROI_58/cropped/ce2/sar.tif（4,733 × 43,653 像素），每 73 × 73 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_058.html#本页数字从哪来", "href": "docs/rois/ROI_058.html#本页数字从哪来", "title": "ROI_058", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_056.html", "href": "docs/rois/ROI_056.html", "title": "ROI_056", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n296\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_056/\n\n\n对齐控制点\ndata/tie-points/ROI_56/\n\n\n元数据表中的写法\nROI_56"}, {"objectID": "docs/rois/ROI_056.html#概况", "href": "docs/rois/ROI_056.html#概况", "title": "ROI_056", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n296\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_056/\n\n\n对齐控制点\ndata/tie-points/ROI_56/\n\n\n元数据表中的写法\nROI_56"}, {"objectID": "docs/rois/ROI_056.html#mini-rf-条带", "href": "docs/rois/ROI_056.html#mini-rf-条带", "title": "ROI_056", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02321_2CD_EKU_04N130_V1\n官方\n\n\n轨道号\n2321\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-28T07:49:05\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n48.59°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n270.25°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,857 × 55,737 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_056.html#已知问题", "href": "docs/rois/ROI_056.html#已知问题", "title": "ROI_056", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_056.html#缩略图", "href": "docs/rois/ROI_056.html#缩略图", "title": "ROI_056", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 77.5 ~ 124\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.38 ~ -5.281 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_56/cropped/ce2/opt.tif、raw/ROI_56/cropped/ce2/sar.tif（3,359 × 48,899 像素），每 82 × 82 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_056.html#本页数字从哪来", "href": "docs/rois/ROI_056.html#本页数字从哪来", "title": "ROI_056", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_054.html", "href": "docs/rois/ROI_054.html", "title": "ROI_054", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n168\n\n\n带评测真值点的 patch\n145 / 168（86.3%）\n\n\n评测真值点对数\n1,187\n\n\n产物目录\nProcessed_Data/Test/ROI_054/\n\n\n对齐控制点\ndata/tie-points/ROI_54/\n\n\n元数据表中的写法\nROI_54"}, {"objectID": "docs/rois/ROI_054.html#概况", "href": "docs/rois/ROI_054.html#概况", "title": "ROI_054", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n168\n\n\n带评测真值点的 patch\n145 / 168（86.3%）\n\n\n评测真值点对数\n1,187\n\n\n产物目录\nProcessed_Data/Test/ROI_054/\n\n\n对齐控制点\ndata/tie-points/ROI_54/\n\n\n元数据表中的写法\nROI_54"}, {"objectID": "docs/rois/ROI_054.html#mini-rf-条带", "href": "docs/rois/ROI_054.html#mini-rf-条带", "title": "ROI_054", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01526_2CD_EKU_06S233_V1\n官方\n\n\n轨道号\n1526\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-26T22:39:59\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n47.55°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.09°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,765 × 52,703 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.3 m\n实测\n\n\n有效分辨率（方位向）\n18.2 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_054.html#已知问题", "href": "docs/rois/ROI_054.html#已知问题", "title": "ROI_054", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n本 ROI： 测试集里唯一被归入此类的 ROI，重叠面积 86%。它的评测真值点标出的偏移是 dx 约 +17~90 px、dy 约 0，与检验结果方向一致。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）\n\n\n\n\n\n\n\n\n警告Mini-RF 目录里有两个 SAR 文件\n\n\n\nraw/ROI_54/minirf/ 里有两个 SAR 文件，旧代码按文件名排序取第一个。产物与旧版一致，说明当年用的也是这个，只是没有明确规定用哪个。\n出处：2026-09-11 数据核查会话\n\n\n\n\n\n\n\n\n警告与 ROI_017 的范围部分重叠\n\n\n\n与训练集的 ROI_017 范围重叠 57%，但 patch 级只有 17 个 patch 有重叠、且都不超过 16%，当时判断可接受。\n出处：旧参考文档 DATA_REFERENCE.md §4"}, {"objectID": "docs/rois/ROI_054.html#缩略图", "href": "docs/rois/ROI_054.html#缩略图", "title": "ROI_054", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 77.99 ~ 129.2\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.79 ~ -4.499 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_54/cropped/ce2/opt.tif、raw/ROI_54/cropped/ce2/sar.tif（3,251 × 33,915 像素），每 57 × 57 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_054.html#本页数字从哪来", "href": "docs/rois/ROI_054.html#本页数字从哪来", "title": "ROI_054", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_052.html", "href": "docs/rois/ROI_052.html", "title": "ROI_052", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n170\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_052/\n\n\n对齐控制点\ndata/tie-points/ROI_52/\n\n\n元数据表中的写法\nROI_52"}, {"objectID": "docs/rois/ROI_052.html#概况", "href": "docs/rois/ROI_052.html#概况", "title": "ROI_052", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n170\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_052/\n\n\n对齐控制点\ndata/tie-points/ROI_52/\n\n\n元数据表中的写法\nROI_52"}, {"objectID": "docs/rois/ROI_052.html#mini-rf-条带", "href": "docs/rois/ROI_052.html#mini-rf-条带", "title": "ROI_052", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02490_2CD_EKU_16N139_V1\n官方\n\n\n轨道号\n2490\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-10T15:12:15\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n48.80°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n90.92°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,066 × 65,753 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.0 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_052.html#已知问题", "href": "docs/rois/ROI_052.html#已知问题", "title": "ROI_052", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告明显的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（在每对 patch 上找光学与 SAR 的可信匹配、量两者的相对偏移，每个 ROI 按编号等间隔抽 24 对）把这几个 ROI 归为「明显错位」：patch 对的重叠面积中位数 66%~79%。偏移几乎都在 x 方向（横跨条带），y 方向基本为 0；错位程度与该 ROI 对齐控制点的拟合残差对得上。\n这项检验只能当参考：它能证明一对 patch「是同一个地方」，证明不了「不是」。待本人复核。\n本 ROI： 对齐控制点中位拟合残差 96 px。\n同一条还涉及：ROI_008、ROI_016、ROI_025、ROI_050。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_052.html#缩略图", "href": "docs/rois/ROI_052.html#缩略图", "title": "ROI_052", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 71.21 ~ 109.9\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.25 ~ -5.048 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_52/cropped/ce2/opt.tif、raw/ROI_52/cropped/ce2/sar.tif（4,780 × 28,874 像素），每 49 × 49 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_052.html#本页数字从哪来", "href": "docs/rois/ROI_052.html#本页数字从哪来", "title": "ROI_052", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_050.html", "href": "docs/rois/ROI_050.html", "title": "ROI_050", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n160\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_050/\n\n\n对齐控制点\ndata/tie-points/ROI_50/\n\n\n元数据表中的写法\nROI_50"}, {"objectID": "docs/rois/ROI_050.html#概况", "href": "docs/rois/ROI_050.html#概况", "title": "ROI_050", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n160\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_050/\n\n\n对齐控制点\ndata/tie-points/ROI_50/\n\n\n元数据表中的写法\nROI_50"}, {"objectID": "docs/rois/ROI_050.html#mini-rf-条带", "href": "docs/rois/ROI_050.html#mini-rf-条带", "title": "ROI_050", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01552_2CD_EKU_18S206_V1\n官方\n\n\n轨道号\n1552\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-28T23:37:58\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n47.62°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.09°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,907 × 59,097 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.5 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_050.html#已知问题", "href": "docs/rois/ROI_050.html#已知问题", "title": "ROI_050", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告明显的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（在每对 patch 上找光学与 SAR 的可信匹配、量两者的相对偏移，每个 ROI 按编号等间隔抽 24 对）把这几个 ROI 归为「明显错位」：patch 对的重叠面积中位数 66%~79%。偏移几乎都在 x 方向（横跨条带），y 方向基本为 0；错位程度与该 ROI 对齐控制点的拟合残差对得上。\n这项检验只能当参考：它能证明一对 patch「是同一个地方」，证明不了「不是」。待本人复核。\n本 ROI： SAR 相对光学整体偏移约 −136 px，约 1 km；对齐控制点中位拟合残差 130 px。\n同一条还涉及：ROI_008、ROI_016、ROI_025、ROI_052。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_050.html#缩略图", "href": "docs/rois/ROI_050.html#缩略图", "title": "ROI_050", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 67.97 ~ 123.8\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.96 ~ -5.085 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_50/cropped/ce2/opt.tif、raw/ROI_50/cropped/ce2/sar.tif（3,215 × 33,394 像素），每 56 × 56 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_050.html#本页数字从哪来", "href": "docs/rois/ROI_050.html#本页数字从哪来", "title": "ROI_050", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_048.html", "href": "docs/rois/ROI_048.html", "title": "ROI_048", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n24\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_048/\n\n\n对齐控制点\ndata/tie-points/ROI_48/\n\n\n元数据表中的写法\nROI_48"}, {"objectID": "docs/rois/ROI_048.html#概况", "href": "docs/rois/ROI_048.html#概况", "title": "ROI_048", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n24\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_048/\n\n\n对齐控制点\ndata/tie-points/ROI_48/\n\n\n元数据表中的写法\nROI_48"}, {"objectID": "docs/rois/ROI_048.html#mini-rf-条带", "href": "docs/rois/ROI_048.html#mini-rf-条带", "title": "ROI_048", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01541_2CD_EKU_03S218_V1\n官方\n\n\n轨道号\n1541\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-28T02:57:52\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n45.52°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.89°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,908 × 59,151 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n18.4 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_048.html#已知问题", "href": "docs/rois/ROI_048.html#已知问题", "title": "ROI_048", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_048.html#缩略图", "href": "docs/rois/ROI_048.html#缩略图", "title": "ROI_048", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 85.75 ~ 124\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.36 ~ -6.514 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_48/cropped/ce2/opt.tif、raw/ROI_48/cropped/ce2/sar.tif（1,287 × 18,896 像素），每 32 × 32 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_048.html#本页数字从哪来", "href": "docs/rois/ROI_048.html#本页数字从哪来", "title": "ROI_048", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_046.html", "href": "docs/rois/ROI_046.html", "title": "ROI_046", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n165\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_046/\n\n\n对齐控制点\ndata/tie-points/ROI_46/\n\n\n元数据表中的写法\nROI_46"}, {"objectID": "docs/rois/ROI_046.html#概况", "href": "docs/rois/ROI_046.html#概况", "title": "ROI_046", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n165\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_046/\n\n\n对齐控制点\ndata/tie-points/ROI_46/\n\n\n元数据表中的写法\nROI_46"}, {"objectID": "docs/rois/ROI_046.html#mini-rf-条带", "href": "docs/rois/ROI_046.html#mini-rf-条带", "title": "ROI_046", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02674_2CD_EKU_42S309_V1\n官方\n\n\n轨道号\n2674\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-25T02:21:07\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.48°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n88.55°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n5,353 × 66,264 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n19.3 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_046.html#缩略图", "href": "docs/rois/ROI_046.html#缩略图", "title": "ROI_046", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 48 ~ 122.6\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.73 ~ -5.125 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_46/cropped/ce2/opt.tif、raw/ROI_46/cropped/ce2/sar.tif（5,194 × 35,734 像素），每 60 × 60 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_046.html#本页数字从哪来", "href": "docs/rois/ROI_046.html#本页数字从哪来", "title": "ROI_046", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_043.html", "href": "docs/rois/ROI_043.html", "title": "ROI_043", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n48\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_043/\n\n\n对齐控制点\ndata/tie-points/ROI_43/\n\n\n元数据表中的写法\nROI_43"}, {"objectID": "docs/rois/ROI_043.html#概况", "href": "docs/rois/ROI_043.html#概况", "title": "ROI_043", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n48\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_043/\n\n\n对齐控制点\ndata/tie-points/ROI_43/\n\n\n元数据表中的写法\nROI_43"}, {"objectID": "docs/rois/ROI_043.html#mini-rf-条带", "href": "docs/rois/ROI_043.html#mini-rf-条带", "title": "ROI_043", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01371_2CD_EKU_23N034_V1\n官方\n\n\n轨道号\n1371\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-14T16:37:17\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.81°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.18°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,434 × 13,660 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_043.html#缩略图", "href": "docs/rois/ROI_043.html#缩略图", "title": "ROI_043", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 56.09 ~ 119.3\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.84 ~ -4.066 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_43/cropped/ce2/opt.tif、raw/ROI_43/cropped/ce2/sar.tif（2,692 × 15,816 像素），每 27 × 27 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_043.html#本页数字从哪来", "href": "docs/rois/ROI_043.html#本页数字从哪来", "title": "ROI_043", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_038.html", "href": "docs/rois/ROI_038.html", "title": "ROI_038", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n64\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_038/\n\n\n对齐控制点\ndata/tie-points/ROI_38/\n\n\n元数据表中的写法\nROI_38"}, {"objectID": "docs/rois/ROI_038.html#概况", "href": "docs/rois/ROI_038.html#概况", "title": "ROI_038", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n64\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_038/\n\n\n对齐控制点\ndata/tie-points/ROI_38/\n\n\n元数据表中的写法\nROI_38"}, {"objectID": "docs/rois/ROI_038.html#mini-rf-条带", "href": "docs/rois/ROI_038.html#mini-rf-条带", "title": "ROI_038", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01437_2CD_EKU_34N326_V1\n官方\n\n\n轨道号\n1437\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-19T21:07:18\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.26°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n267.46°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,294 × 30,291 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n19.1 m\n实测\n\n\n有效分辨率（方位向）\n18.5 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_038.html#已知问题", "href": "docs/rois/ROI_038.html#已知问题", "title": "ROI_038", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告与 ROI_071 的范围部分重叠\n\n\n\n与验证集的 ROI_071 范围重叠 17.5%，patch 级零重叠。\n出处：旧参考文档 DATA_REFERENCE.md §4"}, {"objectID": "docs/rois/ROI_038.html#缩略图", "href": "docs/rois/ROI_038.html#缩略图", "title": "ROI_038", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 38.2 ~ 51.05\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.52 ~ -7.014 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_38/cropped/ce2/opt.tif、raw/ROI_38/cropped/ce2/sar.tif（3,196 × 20,085 像素），每 34 × 34 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_038.html#本页数字从哪来", "href": "docs/rois/ROI_038.html#本页数字从哪来", "title": "ROI_038", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_035.html", "href": "docs/rois/ROI_035.html", "title": "ROI_035", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n214\n\n\n带评测真值点的 patch\n172 / 214（80.4%）\n\n\n评测真值点对数\n1,383\n\n\n产物目录\nProcessed_Data/Val/ROI_035/\n\n\n对齐控制点\ndata/tie-points/ROI_35/\n\n\n元数据表中的写法\nROI_35"}, {"objectID": "docs/rois/ROI_035.html#概况", "href": "docs/rois/ROI_035.html#概况", "title": "ROI_035", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n214\n\n\n带评测真值点的 patch\n172 / 214（80.4%）\n\n\n评测真值点对数\n1,383\n\n\n产物目录\nProcessed_Data/Val/ROI_035/\n\n\n对齐控制点\ndata/tie-points/ROI_35/\n\n\n元数据表中的写法\nROI_35"}, {"objectID": "docs/rois/ROI_035.html#mini-rf-条带", "href": "docs/rois/ROI_035.html#mini-rf-条带", "title": "ROI_035", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02858_2CD_EKU_21S118_V1\n官方\n\n\n轨道号\n2858\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-02-08T13:07:14\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.97°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n88.37°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,273 × 65,234 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_035.html#缩略图", "href": "docs/rois/ROI_035.html#缩略图", "title": "ROI_035", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 54.08 ~ 113.8\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -11.89 ~ -5.284 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_35/cropped/ce2/opt.tif、raw/ROI_35/cropped/ce2/sar.tif（4,725 × 35,001 像素），每 59 × 59 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_035.html#本页数字从哪来", "href": "docs/rois/ROI_035.html#本页数字从哪来", "title": "ROI_035", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_033.html", "href": "docs/rois/ROI_033.html", "title": "ROI_033", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n269\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_033/\n\n\n对齐控制点\ndata/tie-points/ROI_33/\n\n\n元数据表中的写法\nROI_33"}, {"objectID": "docs/rois/ROI_033.html#概况", "href": "docs/rois/ROI_033.html#概况", "title": "ROI_033", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n269\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_033/\n\n\n对齐控制点\ndata/tie-points/ROI_33/\n\n\n元数据表中的写法\nROI_33"}, {"objectID": "docs/rois/ROI_033.html#mini-rf-条带", "href": "docs/rois/ROI_033.html#mini-rf-条带", "title": "ROI_033", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04611_2CD_EKU_51S097_V1\n官方\n\n\n轨道号\n4611\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-06-26T05:43:11\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.70°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n271.89°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n8,030 × 65,188 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n16.9 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_033.html#缩略图", "href": "docs/rois/ROI_033.html#缩略图", "title": "ROI_033", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 43.92 ~ 102.6\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -11.77 ~ -5.604 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_33/cropped/ce2/opt.tif、raw/ROI_33/cropped/ce2/sar.tif（6,240 × 36,859 像素），每 62 × 62 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_033.html#本页数字从哪来", "href": "docs/rois/ROI_033.html#本页数字从哪来", "title": "ROI_033", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_030.html", "href": "docs/rois/ROI_030.html", "title": "ROI_030", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n74\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_030/\n\n\n对齐控制点\ndata/tie-points/ROI_30/\n\n\n元数据表中的写法\nROI_30"}, {"objectID": "docs/rois/ROI_030.html#概况", "href": "docs/rois/ROI_030.html#概况", "title": "ROI_030", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n74\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_030/\n\n\n对齐控制点\ndata/tie-points/ROI_30/\n\n\n元数据表中的写法\nROI_30"}, {"objectID": "docs/rois/ROI_030.html#mini-rf-条带", "href": "docs/rois/ROI_030.html#mini-rf-条带", "title": "ROI_030", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_06689_2CD_EKU_47N288_V1\n官方\n\n\n轨道号\n6689\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-12-06T09:14:59\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.04°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.13°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,846 × 26,903 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n16.6 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_030.html#缩略图", "href": "docs/rois/ROI_030.html#缩略图", "title": "ROI_030", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 39.04 ~ 66.11\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.76 ~ -6.631 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_30/cropped/ce2/opt.tif、raw/ROI_30/cropped/ce2/sar.tif（2,212 × 23,187 像素），每 39 × 39 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_030.html#本页数字从哪来", "href": "docs/rois/ROI_030.html#本页数字从哪来", "title": "ROI_030", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_026.html", "href": "docs/rois/ROI_026.html", "title": "ROI_026", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n190\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_026/\n\n\n对齐控制点\ndata/tie-points/ROI_26/\n\n\n元数据表中的写法\nROI_26"}, {"objectID": "docs/rois/ROI_026.html#概况", "href": "docs/rois/ROI_026.html#概况", "title": "ROI_026", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n190\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_026/\n\n\n对齐控制点\ndata/tie-points/ROI_26/\n\n\n元数据表中的写法\nROI_26"}, {"objectID": "docs/rois/ROI_026.html#mini-rf-条带", "href": "docs/rois/ROI_026.html#mini-rf-条带", "title": "ROI_026", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02769_2CD_EKU_02N210_V1\n官方\n\n\n轨道号\n2769\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-02-01T13:13:39\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n46.92°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n90.23°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,423 × 65,169 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n18.5 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_026.html#已知问题", "href": "docs/rois/ROI_026.html#已知问题", "title": "ROI_026", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_026.html#缩略图", "href": "docs/rois/ROI_026.html#缩略图", "title": "ROI_026", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 76.05 ~ 124.5\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.35 ~ -4.272 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_26/cropped/ce2/opt.tif、raw/ROI_26/cropped/ce2/sar.tif（4,024 × 33,916 像素），每 57 × 57 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_026.html#本页数字从哪来", "href": "docs/rois/ROI_026.html#本页数字从哪来", "title": "ROI_026", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_024.html", "href": "docs/rois/ROI_024.html", "title": "ROI_024", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n239\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_024/\n\n\n对齐控制点\ndata/tie-points/ROI_24/\n\n\n元数据表中的写法\nROI_24"}, {"objectID": "docs/rois/ROI_024.html#概况", "href": "docs/rois/ROI_024.html#概况", "title": "ROI_024", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n239\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_024/\n\n\n对齐控制点\ndata/tie-points/ROI_24/\n\n\n元数据表中的写法\nROI_24"}, {"objectID": "docs/rois/ROI_024.html#mini-rf-条带", "href": "docs/rois/ROI_024.html#mini-rf-条带", "title": "ROI_024", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_03254_2CD_EKU_55S070_V1\n官方\n\n\n轨道号\n3254\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-03-11T15:47:51\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.39°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n86.66°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n11,152 × 49,291 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n37.9 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_024.html#缩略图", "href": "docs/rois/ROI_024.html#缩略图", "title": "ROI_024", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 36.99 ~ 117.5\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.75 ~ -3.823 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_24/cropped/ce2/opt.tif、raw/ROI_24/cropped/ce2/sar.tif（8,666 × 36,859 像素），每 62 × 62 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_024.html#本页数字从哪来", "href": "docs/rois/ROI_024.html#本页数字从哪来", "title": "ROI_024", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_021.html", "href": "docs/rois/ROI_021.html", "title": "ROI_021", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n108\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_021/\n\n\n对齐控制点\ndata/tie-points/ROI_21/\n\n\n元数据表中的写法\nROI_21"}, {"objectID": "docs/rois/ROI_021.html#概况", "href": "docs/rois/ROI_021.html#概况", "title": "ROI_021", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n108\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_021/\n\n\n对齐控制点\ndata/tie-points/ROI_21/\n\n\n元数据表中的写法\nROI_21"}, {"objectID": "docs/rois/ROI_021.html#mini-rf-条带", "href": "docs/rois/ROI_021.html#mini-rf-条带", "title": "ROI_021", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_03028_2CD_EKU_00S302_V1\n官方\n\n\n轨道号\n3028\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-02-21T21:24:18\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.40°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n89.94°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,124 × 66,295 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_021.html#缩略图", "href": "docs/rois/ROI_021.html#缩略图", "title": "ROI_021", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 34.71 ~ 47.87\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.3 ~ -5.974 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_21/cropped/ce2/opt.tif、raw/ROI_21/cropped/ce2/sar.tif（2,497 × 33,916 像素），每 57 × 57 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_021.html#本页数字从哪来", "href": "docs/rois/ROI_021.html#本页数字从哪来", "title": "ROI_021", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_018.html", "href": "docs/rois/ROI_018.html", "title": "ROI_018", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n117\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_018/\n\n\n对齐控制点\ndata/tie-points/ROI_18/\n\n\n元数据表中的写法\nROI_18"}, {"objectID": "docs/rois/ROI_018.html#概况", "href": "docs/rois/ROI_018.html#概况", "title": "ROI_018", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n117\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_018/\n\n\n对齐控制点\ndata/tie-points/ROI_18/\n\n\n元数据表中的写法\nROI_18"}, {"objectID": "docs/rois/ROI_018.html#mini-rf-条带", "href": "docs/rois/ROI_018.html#mini-rf-条带", "title": "ROI_018", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04349_2CD_EKU_50S009_V1\n官方\n\n\n轨道号\n4349\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-06-05T15:57:48\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.40°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n272.83°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n9,039 × 66,104 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n17.0 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_018.html#缩略图", "href": "docs/rois/ROI_018.html#缩略图", "title": "ROI_018", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 68.66 ~ 153.3\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.3 ~ -5.59 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_18/cropped/ce2/opt.tif、raw/ROI_18/cropped/ce2/sar.tif（7,024 × 31,343 像素），每 53 × 53 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_018.html#本页数字从哪来", "href": "docs/rois/ROI_018.html#本页数字从哪来", "title": "ROI_018", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_016.html", "href": "docs/rois/ROI_016.html", "title": "ROI_016", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n265\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_016/\n\n\n对齐控制点\ndata/tie-points/ROI_16/\n\n\n元数据表中的写法\nROI_16"}, {"objectID": "docs/rois/ROI_016.html#概况", "href": "docs/rois/ROI_016.html#概况", "title": "ROI_016", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n265\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_016/\n\n\n对齐控制点\ndata/tie-points/ROI_16/\n\n\n元数据表中的写法\nROI_16"}, {"objectID": "docs/rois/ROI_016.html#mini-rf-条带", "href": "docs/rois/ROI_016.html#mini-rf-条带", "title": "ROI_016", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04363_2CD_EKU_66S352_V1\n官方\n\n\n轨道号\n4363\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-06-06T18:26:02\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n49.95°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n274.65°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n21,282 × 65,900 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.0 m\n实测\n\n\n有效分辨率（方位向）\n18.5 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_016.html#已知问题", "href": "docs/rois/ROI_016.html#已知问题", "title": "ROI_016", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告明显的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（在每对 patch 上找光学与 SAR 的可信匹配、量两者的相对偏移，每个 ROI 按编号等间隔抽 24 对）把这几个 ROI 归为「明显错位」：patch 对的重叠面积中位数 66%~79%。偏移几乎都在 x 方向（横跨条带），y 方向基本为 0；错位程度与该 ROI 对齐控制点的拟合残差对得上。\n这项检验只能当参考：它能证明一对 patch「是同一个地方」，证明不了「不是」。待本人复核。\n本 ROI： 对齐控制点中位拟合残差 128 px。\n同一条还涉及：ROI_008、ROI_025、ROI_050、ROI_052。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_016.html#缩略图", "href": "docs/rois/ROI_016.html#缩略图", "title": "ROI_016", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 1 ~ 165.1\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.35 ~ -4.649 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_16/cropped/ce2/opt.tif、raw/ROI_16/cropped/ce2/sar.tif（11,444 × 39,190 像素），每 66 × 66 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_016.html#本页数字从哪来", "href": "docs/rois/ROI_016.html#本页数字从哪来", "title": "ROI_016", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_013.html", "href": "docs/rois/ROI_013.html", "title": "ROI_013", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n54\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_013/\n\n\n对齐控制点\ndata/tie-points/ROI_13/\n\n\n元数据表中的写法\nROI_13"}, {"objectID": "docs/rois/ROI_013.html#概况", "href": "docs/rois/ROI_013.html#概况", "title": "ROI_013", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n54\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_013/\n\n\n对齐控制点\ndata/tie-points/ROI_13/\n\n\n元数据表中的写法\nROI_13"}, {"objectID": "docs/rois/ROI_013.html#mini-rf-条带", "href": "docs/rois/ROI_013.html#mini-rf-条带", "title": "ROI_013", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02464_2CD_EKU_37S167_V1\n官方\n\n\n轨道号\n2464\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-08T14:29:05\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.68°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n88.42°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n5,390 × 65,083 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.0 m\n实测\n\n\n有效分辨率（方位向）\n18.4 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_013.html#缩略图", "href": "docs/rois/ROI_013.html#缩略图", "title": "ROI_013", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 41.2 ~ 102.1\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.35 ~ -5.193 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_13/cropped/ce2/opt.tif、raw/ROI_13/cropped/ce2/sar.tif（4,189 × 11,987 像素），每 20 × 20 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_013.html#本页数字从哪来", "href": "docs/rois/ROI_013.html#本页数字从哪来", "title": "ROI_013", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_011.html", "href": "docs/rois/ROI_011.html", "title": "ROI_011", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n92\n\n\n带评测真值点的 patch\n83 / 92（90.2%）\n\n\n评测真值点对数\n706\n\n\n产物目录\nProcessed_Data/Test/ROI_011/\n\n\n对齐控制点\ndata/tie-points/ROI_11/\n\n\n元数据表中的写法\nROI_11"}, {"objectID": "docs/rois/ROI_011.html#概况", "href": "docs/rois/ROI_011.html#概况", "title": "ROI_011", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n92\n\n\n带评测真值点的 patch\n83 / 92（90.2%）\n\n\n评测真值点对数\n706\n\n\n产物目录\nProcessed_Data/Test/ROI_011/\n\n\n对齐控制点\ndata/tie-points/ROI_11/\n\n\n元数据表中的写法\nROI_11"}, {"objectID": "docs/rois/ROI_011.html#mini-rf-条带", "href": "docs/rois/ROI_011.html#mini-rf-条带", "title": "ROI_011", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02689_2CD_EKU_16S293_V1\n官方\n\n\n轨道号\n2689\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-26T06:29:37\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.41°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n89.29°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,199 × 66,241 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_011.html#已知问题", "href": "docs/rois/ROI_011.html#已知问题", "title": "ROI_011", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告目录里有别处遗留的控制点文件\n\n\n\nopt_tie.txt / opt_tie.prj（也随仓库入库在 data/tie-points/ROI_11/cropped/）是别处遗留的文件，流程没用到，但容易让人误以为与本 ROI 的 opt_tie.pts 是同一批点。\n出处：2026-09-11 数据核查会话"}, {"objectID": "docs/rois/ROI_011.html#缩略图", "href": "docs/rois/ROI_011.html#缩略图", "title": "ROI_011", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 63.03 ~ 101.4\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.99 ~ -4.621 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_11/cropped/ce2/opt.tif、raw/ROI_11/cropped/ce2/sar.tif（3,761 × 29,483 像素），每 50 × 50 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_011.html#本页数字从哪来", "href": "docs/rois/ROI_011.html#本页数字从哪来", "title": "ROI_011", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_009.html", "href": "docs/rois/ROI_009.html", "title": "ROI_009", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n162\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_009/\n\n\n对齐控制点\ndata/tie-points/ROI_9/\n\n\n元数据表中的写法\nROI_9"}, {"objectID": "docs/rois/ROI_009.html#概况", "href": "docs/rois/ROI_009.html#概况", "title": "ROI_009", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n162\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_009/\n\n\n对齐控制点\ndata/tie-points/ROI_9/\n\n\n元数据表中的写法\nROI_9"}, {"objectID": "docs/rois/ROI_009.html#mini-rf-条带", "href": "docs/rois/ROI_009.html#mini-rf-条带", "title": "ROI_009", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02041_2CD_EKU_04N061_V1\n官方\n\n\n轨道号\n2041\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-06T08:00:54\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.47°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n271.01°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n1,881 × 33,525 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.3 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_009.html#已知问题", "href": "docs/rois/ROI_009.html#已知问题", "title": "ROI_009", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告局部错位，错开的距离随位置变化\n\n\n\n2026-09-11 的配对检验抽样时几乎找不到可信匹配，随后把 162 对全部跑了一遍：29 对（18%）找到了可信匹配（对照组 ROI_12 为 70%）。纹理指数与对照组相近（光学 3.39 / 2.52 对 3.62 / 2.58），排除了纹理平淡。找到匹配的 patch 显示并没有配错片，但 SAR 相对光学的横向偏移分段变化：\n\n\n\n光学窗口所在行\n偏移 dx（像素）\n\n\n\n\n3072 ~ 5632\n一对都没找到\n\n\n6144 ~ 8704\n+88 ~ +128\n\n\n9216 ~ 14848\n−96 ~ −108\n\n\n15360 ~ 17920\n−188 ~ −216\n\n\n18432 ~ 24064\n−64 ~ +36\n\n\n\n对齐控制点的拟合残差中位 73 px、最大 227 px。原因未查明，待本人复核。\n出处：2026-09-11 数据核查会话（配对检验，全量）"}, {"objectID": "docs/rois/ROI_009.html#缩略图", "href": "docs/rois/ROI_009.html#缩略图", "title": "ROI_009", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 47.03 ~ 93.24\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.75 ~ -6.311 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_9/cropped/ce2/opt.tif、raw/ROI_9/cropped/ce2/sar.tif（2,211 × 33,916 像素），每 57 × 57 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_009.html#本页数字从哪来", "href": "docs/rois/ROI_009.html#本页数字从哪来", "title": "ROI_009", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_007.html", "href": "docs/rois/ROI_007.html", "title": "ROI_007", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n372\n\n\n带评测真值点的 patch\n286 / 372（76.9%）\n\n\n评测真值点对数\n2,315\n\n\n产物目录\nProcessed_Data/Test/ROI_007/\n\n\n对齐控制点\ndata/tie-points/ROI_7/\n\n\n元数据表中的写法\nROI_7"}, {"objectID": "docs/rois/ROI_007.html#概况", "href": "docs/rois/ROI_007.html#概况", "title": "ROI_007", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n372\n\n\n带评测真值点的 patch\n286 / 372（76.9%）\n\n\n评测真值点对数\n2,315\n\n\n产物目录\nProcessed_Data/Test/ROI_007/\n\n\n对齐控制点\ndata/tie-points/ROI_7/\n\n\n元数据表中的写法\nROI_7"}, {"objectID": "docs/rois/ROI_007.html#mini-rf-条带", "href": "docs/rois/ROI_007.html#mini-rf-条带", "title": "ROI_007", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_05098_2CD_EKU_50N140_V1\n官方\n\n\n轨道号\n5098\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-08-03T10:40:37\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.66°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n92.54°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n9,101 × 65,408 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n52.6 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_007.html#缩略图", "href": "docs/rois/ROI_007.html#缩略图", "title": "ROI_007", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 48.61 ~ 125.1\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.32 ~ -5.285 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_7/cropped/ce2/opt.tif、raw/ROI_7/cropped/ce2/sar.tif（5,570 × 66,654 像素），每 112 × 112 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_007.html#本页数字从哪来", "href": "docs/rois/ROI_007.html#本页数字从哪来", "title": "ROI_007", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_005.html", "href": "docs/rois/ROI_005.html", "title": "ROI_005", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n135\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_005/\n\n\n对齐控制点\ndata/tie-points/ROI_5/\n\n\n元数据表中的写法\nROI_5"}, {"objectID": "docs/rois/ROI_005.html#概况", "href": "docs/rois/ROI_005.html#概况", "title": "ROI_005", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n135\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_005/\n\n\n对齐控制点\ndata/tie-points/ROI_5/\n\n\n元数据表中的写法\nROI_5"}, {"objectID": "docs/rois/ROI_005.html#mini-rf-条带", "href": "docs/rois/ROI_005.html#mini-rf-条带", "title": "ROI_005", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04956_2CD_EKU_34N286_V1\n官方\n\n\n轨道号\n4956\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-07-23T06:54:56\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.97°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n92.25°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,708 × 66,629 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.6 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_005.html#缩略图", "href": "docs/rois/ROI_005.html#缩略图", "title": "ROI_005", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 36.04 ~ 66.85\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -16.22 ~ -6.695 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_5/cropped/ce2/opt.tif、raw/ROI_5/cropped/ce2/sar.tif（4,568 × 34,245 像素），每 58 × 58 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_005.html#本页数字从哪来", "href": "docs/rois/ROI_005.html#本页数字从哪来", "title": "ROI_005", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_002.html", "href": "docs/rois/ROI_002.html", "title": "ROI_002", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n152\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_002/\n\n\n对齐控制点\ndata/tie-points/ROI_2/\n\n\n元数据表中的写法\nROI_2"}, {"objectID": "docs/rois/ROI_002.html#概况", "href": "docs/rois/ROI_002.html#概况", "title": "ROI_002", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n152\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_002/\n\n\n对齐控制点\ndata/tie-points/ROI_2/\n\n\n元数据表中的写法\nROI_2"}, {"objectID": "docs/rois/ROI_002.html#mini-rf-条带", "href": "docs/rois/ROI_002.html#mini-rf-条带", "title": "ROI_002", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01992_2CD_EKU_06N111_V1\n官方\n\n\n轨道号\n1992\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-02T11:39:27\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.77°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.82°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,308 × 33,158 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_002.html#已知问题", "href": "docs/rois/ROI_002.html#已知问题", "title": "ROI_002", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_002.html#缩略图", "href": "docs/rois/ROI_002.html#缩略图", "title": "ROI_002", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 69.69 ~ 117\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.36 ~ -6.723 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_2/cropped/ce2/opt.tif、raw/ROI_2/cropped/ce2/sar.tif（2,713 × 24,903 像素），每 42 × 42 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_002.html#本页数字从哪来", "href": "docs/rois/ROI_002.html#本页数字从哪来", "title": "ROI_002", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/sources.html", "href": "docs/sources.html", "title": "来源文档", "section": "", "text": "读者带着具体问题进来，找到答案就走：某个字段从哪来、某个参数是多少、去哪核对原文。 数据怎么被做成数据集，看流程文档；最终交付物长什么样，看产物文档。\n每条事实都标了来源，三者的可信度完全不同：", "crumbs": ["首页", "主体文档", "来源文档"]}, {"objectID": "docs/sources.html#官方文档与版本", "href": "docs/sources.html#官方文档与版本", "title": "来源文档", "section": "官方文档与版本", "text": "官方文档与版本\n\n去哪核对原始定义\n\n\n\n文档\n版本\n在这里查什么\n\n\n\n\nMini-RF 数据产品 SIS（Software Interface Specification）\n编号 MRF-4009，2010-02-25 版，变更记录到第 9 次修订（2010-02-20）\n仪器参数（表 1）、Stokes 参数与极化产品定义（§4.3.2.2）、文件命名规则（§4.7.1.1、表 16）\n\n\nMini-RF 产品标签（.LBL，每个条带一份）\nLABEL_REVISION_NOTE = \"2010-JHU/APL Mini-RF LRO Ver. 1\"；DATA_SET_ID = \"LRO-L-MRFLRO-5-CDR-MAP-V1.0\"\n四个波段的名字、入射角、视向、投影与采样间隔、特殊值\n\n\nMini-RF CDR 数据集说明\nLRO-L-MRFLRO-4-CDR-V1.0，发布于 2011-06-15\n数据集层面的说明\n\n\nMini-RF 累积索引\n—\n从产品 ID 查到它所在的归档卷\n\n\nMini-RF PDS 总览、ODE MAPCDR 产品说明\n—\n入口页\n\n\n嫦娥数据发布与信息服务系统\n—\nCE-2 7 m DOM 的下载入口（证书已过期，浏览器会报警）\n\n\n\n版本号、数据集 ID 与所引章节号取自文档与标签原文。[官方] 链接转录自旧参考文档，本轮没有逐一联网核对。[推断] 这些文档的下载副本连同本数据集 67 个条带的官方 .LBL 标签，存放在旧工作区的 docs/ 目录， 没有迁移进本仓库。[实测]\n注意两个数据集 ID 不一样：产品标签写的是 …-5-CDR-MAP-V1.0（地图投影后的 CDR）， 而上表的数据集说明与累积索引属于 …-4-CDR-V1.0。本数据集用的是前者。[官方]，以标签为准。\nCE-2 这边，本仓库没有找到产品规范类的官方文档；下文凡涉及 CE-2 产品本身的描述， 除了能从文件上读出来的，都标为推断。", "crumbs": ["首页", "主体文档", "来源文档"]}, {"objectID": "docs/sources.html#mini-rf-sar", "href": "docs/sources.html#mini-rf-sar", "title": "来源文档", "section": "Mini-RF SAR", "text": "Mini-RF SAR\n\n产品 ID 怎么读\n每个条带有一个产品 ID，同时也是它的文件名（数据盘上是小写的，如 lsz_02833_2cd_eku_16s144_v1.tif）。按 SIS §4.7.1.1 与表 16 逐段解码，以 LSZ_02319_2CD_EKU_23S131_V1 为例：[官方]\n\n\n\n段\n含义\n本例\n\n\n\n\nL\n平台\nLRO\n\n\nS\n频段\nS-band\n\n\nZ\n雷达模式\nZoom\n\n\n02319\n轨道号（开始采集的那一轨）\n2319\n\n\n2\n处理级别\nLevel 2\n\n\nCD\n文件类型\nCalibrated Data Record\n\n\nE\n投影\nEquirectangular\n\n\nK\n分辨率档位\n1024 ppd\n\n\nU\n数值类型\nUnnormalized float\n\n\n23\n中心纬度（取整到度）\n23°\n\n\nS\n纬度半球\n南纬\n\n\n131\n中心经度（取整到度，东经 0–359）\n131°\n\n\nV1\n产品版本\n1\n\n\n\n几点补充：\n\n分辨率档位字母不可信。 本数据集全部条带的档位字母是 K， 按表 16 对应 1024 ppd； 而产品标签里的 MAP_RESOLUTION 是 4,096 ppd，对应的字母应为 M。 两者对不上的条带有 67 个，即全部。以标签（和 GeoTIFF 的像素大小）为准。 [实测]，对照元数据表\nID 里没有成像时间。 要从 ID 查时间，看 GeoTIFF 元数据里的 START_TIME、仓库元数据表的「成像时刻UTC」列， 或在累积索引里按 ID 查。[官方]（SIS §4.7.1.1 的字段表里没有时间段）\n同一个 ID 在仓库的 Mini-RF 元数据表（data/metadata/minirf_metadata.csv）里对得上轨道号、模式、投影三列， 这一点由单元测试逐行核对。[实测]\n\n\n\n四个波段是什么\nMini-RF 是混合极化（hybrid-pol）体制：发射圆极化，相干接收 H、V 两路线极化。 每像素 16 字节，4 个 32 位浮点波段，按波段顺序存放（BAND_SEQUENTIAL）。[官方]，产品标签 BAND_NAME、DESCRIPTION 与 SIS §4.3.2.2.1\n\n\n\n波段\n官方 BAND_NAME\n物理量\n\n\n\n\n1\nH RECEIVE INTENSITY\n⟨|EH|²⟩，H 路接收功率\n\n\n2\nV RECEIVE INTENSITY\n⟨|EV|²⟩，V 路接收功率\n\n\n3\nCROSS POWER INTENSITY (REAL)\nRe⟨EH EV*⟩\n\n\n4\nCROSS POWER INTENSITY (IMAGINARY)\nIm⟨EH EV*⟩\n\n\n\n波段 1、2 是强度（功率），不是幅度；波段 3、4 是交叉功率的实部与虚部，可以为负。 把它们当成四个普通灰度通道去做归一化，会得到没有物理意义的结果。[官方]\n\n\n由四个波段推导的物理量\nSIS §4.3.2.2.1–2 的定义，写成代码：[官方]\nS1 = b1 + b2          # 总功率\nS2 = b1 - b2\nS3 = 2 * b3\nS4 = -2 * b4          # 注意负号，官方定义如此\n\nSC  = 0.5 * (S1 - S4)                        # 同向圆极化（same sense）\nOC  = 0.5 * (S1 + S4)                        # 反向圆极化（opposite sense）\nCPR = SC / OC                                # 圆极化比\nm   = np.sqrt(S2**2 + S3**2 + S4**2) / S1    # 极化度\nSIS 给出的参考值：全月平均 CPR 约为 0.3，全月平均 m 约为 0.6；CPR 接近 0 对应极光滑的地表， 大于 1 对应大尺度块状粗糙面，或厚层冻结挥发物（如水冰）的体散射。[官方]，SIS §4.3.2.2.2.3\nROI 档案页里的 SAR 缩略图画的就是 S1（总功率），取 dB。[实测]\n\n\n仪器参数\nS 波段、Zoom 模式（本数据集全部条带都是这个模式，见下文）的参数，摘自 SIS 表 1：[官方]\n\n\n\n参数\nZoom\nBaseline（对照）\n\n\n\n\n频率\n2.38 GHz（波长 12.6 cm）\n同左\n\n\n极化\n发射 RCP 或 LCP，相干接收 H 与 V\n同左\n\n\n斜距分辨率\n23 m\n115 m\n\n\n地距分辨率\n15 × 30（原表未写单位）\n150 m\n\n\n方位分辨率\n15 × 30（原表未写单位）\n150 m\n\n\n视数\n8\n16\n\n\n线性调频带宽\n8 MHz\n1.6 MHz\n\n\n噪声等效后向散射系数（NESZ）\n−25 dB\n−30 dB\n\n\n条带长度\n&lt; 400 km\n同左\n\n\n极化纯度\n串扰 19 dB，轴比 1.7 dB\n同左\n\n\n\n测绘带宽一项，SIS 表 1 的 S 波段一栏写的是「6 km (baseline)」，X 波段一栏写的是「4 km」， 没有单列 S 波段 Zoom 模式的值。旧参考文档把 4 km 记成了 Zoom 的测绘带宽，这一读法在原表里找不到依据。[官方]\n\n\n格式、特殊值与投影\n\n官方产品是 PDS3 的 IMG + LBL，32 位 IEEE 浮点（PC_REAL）。空值 CORE_NULL = 16#FF7FFFFB#， 约为 −3.4028 × 10³⁸，不是 0。[官方]，产品标签\n投影为等距圆柱（EQUIRECTANGULAR），CENTER_LONGITUDE = 180.0，CENTER_LATITUDE = 0.0（标准纬线一栏写的是 N/A）；月球取球体，半径 1737.4 km； 行星中心坐标（planetocentric），东经为正。[官方]，产品标签 IMAGE_MAP_PROJECTION\n采样间隔：MAP_RESOLUTION = 4096 &lt;pix/deg&gt;，MAP_SCALE = 0.0074031617 &lt;KM/PIXEL&gt;，即约 7.4032 m。[官方]，产品标签\n数据盘 raw/ROI_&lt;n&gt;/minirf/ 里只保留了转换后的 GeoTIFF，原始 IMG/LBL 没有保留。GeoTIFF 的像素大小 就是上面的 MAP_SCALE；nodata 设成了 CORE_NULL 对应的浮点值；PRODUCT_ID、DATA_SET_ID、START_TIME 等标签字段被写进了 GeoTIFF 元数据，所以每个条带都能唯一追回官方归档。[实测]\nROI_054 的 minirf/ 目录里有两个 SAR 文件，旧代码按文件名排序取第一个。[实测]\n\n\n\n本数据集条带的几何与覆盖\n以下数字由仓库里的 Mini-RF 元数据表（从 67 个条带的官方标签逐项抄出）在渲染时汇总， 不手写。逐条带的值见各 ROI 档案页。[官方]，产品标签 → 元数据表\n\n\n\n项\n取值\n\n\n\n\n条带数\n67（每个 ROI 一条）\n\n\n任务阶段\nNOMINAL MISSION\n\n\n模式\nZOOM_S\n\n\n中心频率\n2.3800 GHz\n\n\n投影\nEQUIRECTANGULAR\n\n\nMAP_RESOLUTION\n4096.0 ppd\n\n\n采样间隔\n7.4032 m\n\n\n波段数\n4\n\n\n入射角\n中位 51.70°，范围 45.52–54.92°\n\n\n视向\nLEFT 53 条，RIGHT 14 条\n\n\n条带宽（像素）\n中位 3654，范围 1748–21282\n\n\n条带长（像素）\n中位 65317，范围 7329–99601\n\n\n成像时间（UTC）\n2009-10-14T16:37:17 至 2010-12-06T09:14:59", "crumbs": ["首页", "主体文档", "来源文档"]}, {"objectID": "docs/sources.html#resolution", "href": "docs/sources.html#resolution", "title": "来源文档", "section": "分辨率：标称值与实测值", "text": "分辨率：标称值与实测值\n这一节只列数值。标称值与实测有效分辨率之间的关系尚未研究清楚，本轮不作解释。\n\nSAR\n\n\n\n\n\n\n\n\n量\n数值\n来源\n\n\n\n\n采样间隔\n7.4032 m\n[官方]，产品标签 MAP_SCALE\n\n\n斜距分辨率（标称）\n23 m\n[官方]，SIS 表 1\n\n\n地距 / 方位分辨率（标称）\n15 × 30（原表未写单位），8 视\n[官方]，SIS 表 1\n\n\n实测有效分辨率，距离向\n中位 18.3 m，范围 16.2–54.9 m\n[实测]\n\n\n实测有效分辨率，方位向\n中位 18.7 m，范围 17.9–19.2 m\n[实测]\n\n\n\n实测方法（旧参考文档记载）：在每个条带中部取若干 512 × 512 的全有效块，对取对数后的后向散射 沿行、列方向求功率谱，以「功率谱降到高频噪声底 3 倍以下」处的波长作为有效分辨率。 逐条带数值在元数据表的「实测有效分辨率」两列里。[实测]\n\n\nCE-2 光学\n\n\n\n\n\n\n\n\n量\n数值\n来源\n\n\n\n\n像素大小\n7 m\n[实测]，全部分幅的 geotransform\n\n\n实测有效分辨率\n约 23 m\n[推断]，转述自旧参考文档（方法同上），逐幅数值没有保存，无法复核", "crumbs": ["首页", "主体文档", "来源文档"]}, {"objectID": "docs/sources.html#ce-2-光学", "href": "docs/sources.html#ce-2-光学", "title": "来源文档", "section": "CE-2 光学", "text": "CE-2 光学\n\n产品\n\n嫦娥二号 CCD 立体相机的 7 m 分辨率全月数字正射影像（DOM）。拿到手的是正射成品， 属 CE2TMap2015 系列，由 100 km 轨道的影像制作；地面段已完成辐射定标、光度校正、几何校正、 影像匹配与分幅镶嵌；全月分为 844 幅。 [推断]，转述自旧参考文档，本仓库没有找到官方原文\n下载入口是嫦娥数据发布与信息服务系统的「月图浏览」，选 7 米分辨率 DOM 产品，按经纬度检索， 得到 tif + tfw + prj 文件包。[推断]，出自旧的《数据下载教程》\n单波段，8 位无符号整型；像素 7 m × 7 m。[实测]\n投影信息的存放方式不统一：有的 ROI 目录里带旁挂的 .prj/.tfw，有的只把坐标系嵌在 GeoTIFF 里； 还有个别分幅（如 ROI_28 的 G123）GeoTIFF 里没有坐标系，只能靠旁挂的 .prj。[实测]\n\n\n\n分幅命名\n分幅文件名形如 CE2_GRAS_DOM_07m_G203_03N161W_A，中间两段是分幅编号与名义位置：[推断]，由本数据集用到的全部分幅的名字与 geotransform 归纳\n\n\n\n段\n本例\n含义\n\n\n\n\n纬度带字母\nG\n见下表\n\n\n行号\n2\n每条带分南北两行，各占 7°，1 在北、2 在南\n\n\n列号\n03\n从西经 180° 起向东编号，每列的经度宽度随纬度带不同\n\n\n名义纬度\n03N\n本幅中心附近的纬度，取整到度\n\n\n名义经度\n161W\n本幅中心附近的经度，取整到度，东西经分开写\n\n\n\n按这套规则从名字算出的经纬范围，与本数据集用到的全部分幅用 geotransform 反算的实测范围一致 （相差不超过 0.03°）。[实测]\n\n\n分带墨卡托投影参数\n南北纬 70° 以内按纬度带分幅，每带一套墨卡托投影，参数只有标准纬线 lat_ts 随带变化，其余全部相同：[实测]，全部分幅的 .prj 或 GeoTIFF 内嵌坐标系\n\n投影：墨卡托（GDAL 读作 Mercator_2SP）\n月球球体，半径 1737400 m（Moon_2000_IAU_IAG）\n中央经线 0°，东偏移与北偏移均为 0\n像素 7 m × 7 m\n\n\n\n\n纬度带\n纬度范围\nlat_ts\n每幅经度宽\n每行幅数\n\n\n\n\nC\n56°N – 70°N\n+63°\n15°\n24\n\n\nD\n42°N – 56°N\n+49°\n10°\n36\n\n\nE\n28°N – 42°N\n+35°\n9°\n40\n\n\nF\n14°N – 28°N\n+21°\n8°\n45\n\n\nG\n0° – 14°N\n+7°\n7.5°\n48\n\n\nH\n14°S – 0°\n-7°\n7.5°\n48\n\n\nI\n28°S – 14°S\n-21°\n8°\n45\n\n\nJ\n42°S – 28°S\n-35°\n9°\n40\n\n\nK\n56°S – 42°S\n-49°\n10°\n36\n\n\nL\n70°S – 56°S\n-63°\n15°\n24\n\n\n\n这张表由 moondata.sources.CE2_BANDS 生成；lat_ts 取自各带没有出过问题的分幅，纬度范围与经度宽 由分幅名与 geotransform 归纳，并用单元测试对照过实测范围。[实测]\n补充几条：\n\nlat_ts 的数值恰好等于本带的中间纬度。[推断]\n有的北半球分幅 lat_ts 写成了负值（如 G208、G242 写的是 −7°）。墨卡托投影只取标准纬线的余弦， 正负号不改变结果，所以这不算错误。[实测]\n70° 以外的极区用极射赤面投影（标准纬线 ±80°），分幅字母为 N、S。本数据集没有用到， 只在不属于数据集的 ROI_4、ROI_14、ROI_19 的原始目录里出现过。[实测]\n\n\n\nlat_ts 被改错的 5 幅\n即页首警告里的那 5 幅。[实测]，逐幅读 GeoTIFF 内嵌坐标系\n\n\n\n分幅\n所在带应有的 lat_ts\n文件里写的\n用到它的 ROI\n\n\n\n\nE215_31N049W\n35°\n21°\nROI_073\n\n\nE218_31N022W\n35°\n21°\nROI_057\n\n\nE219_31N013W\n35°\n21°\nROI_058\n\n\nI219_24S032W\n−21°\n−35°\nROI_070\n\n\nI236_24S104E\n−21°\n−35°\nROI_065\n\n\n\n据旧代码的注释：这几幅在 2025-10-30 被重新写过，坐标系换成了相邻纬度带的，原因多半是当时为了让两幅 能镶嵌而「统一」了坐标系；现有 patch 产物在那之前就做好了，所以没受影响。[推断]\n同样据旧代码注释：用错误的 lat_ts 读，这几幅与 Mini-RF 的重叠区会少掉 30%～60%； 把 lat_ts 改回本带的值后，用 SIFT 与旧产物逐点比对，中位误差 7～44 m。[实测]，旧代码作者当时所测", "crumbs": ["首页", "主体文档", "来源文档"]}, {"objectID": "docs/sources.html#overturned", "href": "docs/sources.html#overturned", "title": "来源文档", "section": "已被推翻的旧结论", "text": "已被推翻的旧结论\n旧参考文档第 4 节曾把部分 ROI 的局部错位归因于地形与缺少高程数据（现存版本里已找不到这句），这条归因已被推翻，本文档不采用。 作者的结论是：错位来自对齐时的全局拟合残差，再叠加条带极端的长宽比（见各 ROI 档案页里的「局部错位」条目）。 这一结论还没有写成附证据的研究笔记，留给数据集特性研究。[推断]", "crumbs": ["首页", "主体文档", "来源文档"]}, {"objectID": "docs/dataset-study.html", "href": "docs/dataset-study.html", "title": "数据集特性研究", "section": "", "text": "注记这一部分现在是空的，而且是有意空着的\n\n\n\n本轮（issue #4）只在导航里为它留一个位置，不产出任何内容。 下面写的是将来往这里放什么、以什么形式放，不是结论。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}, {"objectID": "docs/dataset-study.html#将来放什么", "href": "docs/dataset-study.html#将来放什么", "title": "数据集特性研究", "section": "将来放什么", "text": "将来放什么\n数据集本身的性质问题——不是「它怎么被做出来的」（那是流程文档），而是 「它是什么样的、有什么毛病、某个现象为什么会这样」。已经知道存在、但本轮明确不碰的， 例如：若干 ROI 的局部错位、若干 ROI 的 SAR 距离向有效分辨率异常、 窗口清单与实际产物的数量差、部分 ROI 是否残留旧的重采样网纹。\n人工标注的质量至今没有评估过。这是将来必做的一项，本轮完全不碰—— 在它做完之前，任何基于评测真值点得出的精度数字都建立在一个未经检验的前提上。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}, {"objectID": "docs/dataset-study.html#以什么形式放", "href": "docs/dataset-study.html#以什么形式放", "title": "数据集特性研究", "section": "以什么形式放", "text": "以什么形式放\n一个问题一篇，笔记式，不预先搭章节结构。每篇包含问题、证据、结论， 并且保留已经被证伪的假设：走过的死路和它为什么是死路，与结论同样值得写下来， 否则接手的人会把同一条路再走一遍。\n之所以不在这里先摆出一排空标题，是因为章节结构会反过来规定研究该往哪走。 等真有了第一篇再谈结构。\n笔记可以是 .qmd，也可以直接是 .ipynb——Quarto 两种都能渲染成站点的一页， 不需要为此改工具链。", "crumbs": ["首页", "数据集特性研究（本轮未产出）"]}, {"objectID": "index.html", "href": "index.html", "title": "月球光学–SAR 配准数据集", "section": "", "text": "这里是这个数据集的全部说明材料。数据集已经冻结，955 GB 影像不在仓库里； 这个站点要回答的是：它是什么、从哪来、怎么被做成这样、以及你拿到的是什么。", "crumbs": ["首页"]}, {"objectID": "index.html#怎么读", "href": "index.html#怎么读", "title": "月球光学–SAR 配准数据集", "section": "怎么读", "text": "怎么读\n什么都不用装。 站点的构建产物随仓库一起提交，克隆下来双击 _site/index.html 就能看——不需要 Python、不需要 Quarto、不需要联网，也不需要接那块移动硬盘。\n左边是导航树，右边是本页目录，右上角的搜索框搜全站正文（中文可用）。\n\n\n\n\n\n\n提示第一次来，先读术语表\n\n\n\n尤其是对齐控制点与评测真值点的区别，以及坐标符号约定。 前者错了会让评测结论失效，后者错了会让配准结果整体镜像——而且两种错误都不报错。", "crumbs": ["首页"]}, {"objectID": "index.html#数据集是怎么来的", "href": "index.html#数据集是怎么来的", "title": "月球光学–SAR 配准数据集", "section": "数据集是怎么来的", "text": "数据集是怎么来的\n\n\n\n\n\nflowchart LR\n  A[\"① 算重叠区&lt;br/&gt;光学 ∩ SAR\"] --&gt; B[\"② 标对齐控制点&lt;br/&gt;人工，ENVI\"]\n  B --&gt; C[\"③ 估计全局变换&lt;br/&gt;每 ROI 一个\"]\n  C --&gt; D[\"④ 正向算窗口&lt;br/&gt;切 patch\"]\n  B -.-&gt; E[[\"不可再生&lt;br/&gt;已入库 data/\"]]\n  D --&gt; F[\"数据集&lt;br/&gt;67 个 ROI\"]\n\n\n\n\n\n\n第 ② 步是人工的，无法自动复现，所以那批标注被当作数据纳入版本控制 （仓库里的 data/README.md）。 其余三步要求正向计算：不读任何历史产物的位置信息，独立算出与现有数据集一致的结果。\n代码的顶层模块与这四步一一对应，所以目录结构本身就是上面这张图。", "crumbs": ["首页"]}, {"objectID": "index.html#站点里有什么", "href": "index.html#站点里有什么", "title": "月球光学–SAR 配准数据集", "section": "站点里有什么", "text": "站点里有什么\n\n\n\n\n内容\n状态\n\n\n\n\n术语表\n词汇与坐标符号约定\n本轮产出\n\n\n来源文档\n数据从哪来：官方文档、产品 ID、投影、波段\n已产出\n\n\n流程文档\n它如何被做成这样\n尚未产出（issue #11）\n\n\n产物文档\n你拿到的是什么：目录、命名、类型、数量、真值点覆盖\n已产出\n\n\nROI 档案\n每个 ROI 一页：条带参数、patch 数、缩略图、已知问题\n已产出\n\n\n数据集特性研究\n一个问题一篇的研究笔记\n本轮不产出，仅留位\n\n\n\n文档里的统计数字都从统计快照取值，不手写——快照由 moondata scan 从真实数据扫描生成， 随仓库提交，所以数字不会在无人察觉时过期，移动硬盘没插时文档也照样渲染。", "crumbs": ["首页"]}, {"objectID": "index.html#怎么重新构建", "href": "index.html#怎么重新构建", "title": "月球光学–SAR 配准数据集", "section": "怎么重新构建", "text": "怎么重新构建\nquarto render\n一条命令，产出提交到 _site/。改完 .qmd 记得重跑一次，否则读者看到的还是旧的。", "crumbs": ["首页"]}, {"objectID": "CONTEXT.html", "href": "CONTEXT.html", "title": "术语表", "section": "", "text": "本文件是本项目的词汇表：每条只给定义与中英对照，不讲实现、不给操作步骤、 不放统计数字。要知道数据从哪来、怎么被做成这样、最终长什么样，看主体文档。\n词汇表放在仓库根而不是只放在文档站里，是因为它同时服务两类读者：读文档站的人， 以及只有一个终端、正要动手改代码的人（含 agent）。两边看到的是同一份文件—— 文档站里的这一页就是 CONTEXT.md 本身渲染出来的，不存在第二份会漂的副本。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#影像与区域", "href": "CONTEXT.html#影像与区域", "title": "术语表", "section": "影像与区域", "text": "影像与区域\n\nROI（region of interest，感兴趣区）\n一块光学与 SAR 同时覆盖的月表区域，是本数据集的组织单位。编号形如 ROI_35。 每个 ROI 有自己的一对对齐影像、一套对齐控制点、一批 patch。\n\n\n光学影像（optical image）\n嫦娥二号（CE-2）7 m 分辨率数字正射影像（DOM）。单波段，8 位无符号整型。\n\n\nSAR 影像（SAR image）\nMini-RF 雷达影像。四波段，32 位浮点，含负值。\n\n\n对齐影像（aligned image）\n一个 ROI 的光学与 SAR 被重采样到同一网格后的那一对大图。patch 从它上面切出来， 对齐控制点也标在它上面。\n\n\npatch（切片）\n从对齐影像上按固定尺寸切下来的小图，光学与 SAR 一一对应，同编号即同一块地面。 它是数据集对外交付的最小单位，也是评测真值点唯一存在的地方。 中文里不译，沿用 patch——既有代码、目录名与文件名全都是这个词。\n\n\n划分（split）\nTrain / Val / Test，按 ROI 划分，不按 patch 划分：同一个 ROI 的全部 patch 落在同一个划分里。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#两种同名点这两条必须分清", "href": "CONTEXT.html#两种同名点这两条必须分清", "title": "术语表", "section": "两种同名点（这两条必须分清）", "text": "两种同名点（这两条必须分清）\n「同名点」（tie point / corresponding point）指一对指向同一地物的坐标——一个在光学上， 一个在 SAR 上。本项目里有两批同名点，它们的标注位置、数量级、覆盖范围和用途 完全不同，混用会直接导致错误结论。\n\n对齐控制点（alignment tie points）\n\n标在哪 —— 人工在 ENVI 中于对齐影像（整幅大图）上标注。\n多少 —— 每个 ROI 约 30 对。\n覆盖 —— 全部 67 个 ROI，三个划分都有。\n用途 —— 求解该 ROI 的全局变换，进而决定 patch 切在哪。它是生产资料。\n不是什么 —— 不是评测的金标准。拿它去评测，等于用造数据的那把尺子量数据自己。\n\n\n\n评测真值点（evaluation ground truth）\n\n标在哪 —— 人工在单个 patch 上标注。\n多少 —— 每个 patch 约 8 对。\n覆盖 —— 只存在于验证集与测试集，且只覆盖其中约 82% 的 patch； 训练集完全没有。\n用途 —— 评测配准算法的精度。它是评测基准。\n\n\n\n为什么按用途命名\n这两批点在既有代码与文件名里被叫作 tie 和 label，口头上则常被称作「大图上的点」 与「小图上的点」。文档一律使用上面两个专名，因为按位置命名解释不了 「训练集为什么没有后者」，而按用途命名，答案自明：训练集不需要被评测。\n文件名与文件格式保持现状不改——它们是格式契约，既有数据和既有代码都按它读写。 改的只是我们讲话时用的词。\n\n\n生成标签（generated labels）\n\n怎么来 —— 不是人标的：patch 内取一组规则网格点，用全局变换算出它们在 SAR patch 上的位置。精度因此完全取决于对齐控制点拟合出的那个变换。\n格式 —— 与评测真值点同一种文件格式（Label/patch_&lt;n&gt;.txt，y 取负）。\n不是什么 —— 不是评测真值点，不能拿来评测；也不能拿去替换验证集与测试集上 人工标的那一份。代码把它写在工作目录里，不写回数据盘。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#坐标符号约定coordinate-sign-convention", "href": "CONTEXT.html#坐标符号约定coordinate-sign-convention", "title": "术语表", "section": "坐标符号约定（coordinate sign convention）", "text": "坐标符号约定（coordinate sign convention）\n\n\n\n\n\n\n重要弄错了不会报错，只会算出镜像的结果\n\n\n\n三种同名点文件对 y 的符号处理不一致，而三者都是纯文本的数字列。取错符号的产物 在数值上完全正常、打开看也完全正常，只有配准结果整体沿水平轴翻转——没有任何一步 会抛异常。这是本项目最容易静默出错的地方，所以它被钉进词汇表。\n\n\n\n\n\n\n\n\n\n\n\n文件\n内容\n坐标\ny 的符号\n\n\n\n\nLabel/patch_&lt;n&gt;.txt\n评测真值点（或生成标签）\npatch 内像素\n取负\n\n\ncropped/opt_tie.pts\n对齐控制点\n对齐影像像素\n不取负\n\n\ncropped/opt_tie.txt\n对齐控制点\n地图坐标（米）\n不取负\n\n\n\n约定：包内一律用不取负的 y（向下为正的像素行号），取负只是标签文件的磁盘格式。 因此符号转换只发生在读写边界——读标签文件时取一次负，写标签文件时再取一次负， 中间所有计算、所有内存中的数组，y 都是正的。任何在中途翻符号的代码都是错的。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#复现与验收", "href": "CONTEXT.html#复现与验收", "title": "术语表", "section": "复现与验收", "text": "复现与验收\n\n窗口（window）\n一个 patch 在对齐影像上的位置，记作左上角像素坐标加固定的 patch 尺寸。 「算窗口」与「切 patch」是两件事。窗口落在哪是纯几何，不读影像；窗口留不留 要看两块 patch 里有没有 nodata 像素，那要读筛选影像。切 patch 读的则是另一版对齐影像。\n\n\n筛选影像（selection images）\n按当年切片时的做法（光学一次、SAR 两次最近邻重采样）从原始输入重做的一对对齐影像， 只用来判窗口留不留，不从它上面切 patch。数据盘上现在的对齐影像已用 cubic 重做过， nodata 边缘与当年差一两个像素，拿它判会多留下几个贴边的窗口，其后的编号随之整体错位。\n\n\n窗口清单（window manifest）\ndata/windows/ 下逐 ROI 记录网格与全部窗口坐标的 JSON。\n它的用途发生过一次转变：最初是从已有 patch 反推出来的，为的是重切之后 「网格、窗口、编号」三者不变，从而让 patch 上的评测真值点继续成立；现在它是 正向复现的验收基准——新代码正向算出的窗口必须与它逐条相等。同一份文件， 两种截然不同的用途。\n\n\n正向复现（forward reproduction）\n从原始输入与对齐控制点独立算出现有数据集，不读取任何历史产物的位置信息。 这是本项目对代码的核心要求，也是「第二版代码读着旧 patch 反推着切」这一做法被废弃的原因。\n\n\n一级验收 / 二级验收（level-1 / level-2 acceptance）\n\n一级：正向算出的窗口与窗口清单逐条相等（位置与编号都相等）。比对本身不读影像，快。\n二级：切出的 patch 与现有产物逐字节一致。要读影像，慢。在逐字节之前先依次回答 三个问题，次序固定：位置变没变 → 数据丢没丢 → 网纹消没消。前两项是正确性， 第三项是改进目标，只记录。\n\n\n\n冻结（frozen）\n验证集与测试集不再重切。原因是人工标注的评测真值点会随重切而作废， 不是数据本身有问题。训练集不受这条约束——它没有评测真值点，没有什么会作废。", "crumbs": ["首页", "术语表"]}, {"objectID": "CONTEXT.html#工作区", "href": "CONTEXT.html#工作区", "title": "术语表", "section": "工作区", "text": "工作区\n\n数据根（data root）\n955 GB 影像所在目录的本机路径。影像不进仓库，靠它引用；不同机器挂载点不同， 所以它可配置（--data-root → MOONDATA_DATA_ROOT → moondata.toml，取第一个非空的）。\n\n\n统计快照（statistics snapshot）\nstats/snapshot.json。从真实数据扫描出来的统计量，携带生成时间与一枚数据指纹。 文档只读快照，不读影像——所以移动硬盘没插时文档照样渲染。\n\n\n删除清单（removal manifest）\n删除某个 ROI 的 patch 产物时留下的文件清单：写明删了什么、为什么、何时删，并逐行列出 被删文件的相对路径。它是被删 ROI 唯一的剩余记录，统计「含已删除 ROI」口径的数量 全靠它。目前只有一份：ROI_60（与 ROI_37 逐像素重复）。\n\n\n数据指纹（data fingerprint）\n刻画数据根目录形态（相对路径 + 文件大小）的摘要，不是像素内容的哈希。 它回答的是「快照还作不作数」。", "crumbs": ["首页", "术语表"]}, {"objectID": "docs/products.html", "href": "docs/products.html", "title": "产物文档", "section": "", "text": "注记本页每一个数字都来自统计快照\n\n\n\n快照 stats/snapshot.json 生成于 2026-09-23T07:25:37+08:00， 所依据的数据指纹为 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb （数据根下 24,914 个文件，共 956.1 GiB）。 指纹覆盖的是整个数据根（含原始影像），而本页的统计量只来自其中的 patch 产物—— 所以原始影像那边有变动也会让指纹「不一致」，这时本页数字未必真的过期，重扫一次即可确认。\n正文里没有手写的数字：页面渲染时从快照取值，所以移动硬盘没插也照样渲染。 想知道这些数字是否仍然作数，接上盘跑 moondata doctor，看指纹是否「一致」； 不一致就跑 moondata scan 重新生成快照，再 quarto render。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#目录结构", "href": "docs/products.html#目录结构", "title": "产物文档", "section": "目录结构", "text": "目录结构\npatch 产物在数据根下的 Processed_Data/ 里，按划分 → ROI → 模态三层组织：\nProcessed_Data/\n├── Train/\n│   └── ROI_&lt;nnn&gt;/\n│       ├── Optical/   patch_&lt;n&gt;.tif    光学 patch\n│       └── SAR/       patch_&lt;n&gt;.tif    SAR patch\n├── Val/\n│   └── ROI_&lt;nnn&gt;/\n│       ├── Optical/\n│       ├── SAR/\n│       └── Label/     patch_&lt;n&gt;.txt    评测真值点\n│                      patch_&lt;n&gt;.prj    标注软件随手写下的投影文件\n└── Test/              同 Val\n\n划分按 ROI 切，不按 patch 切：同一个 ROI 的全部 patch 落在同一个划分里。\nLabel/ 只出现在Val、Test，训练集没有这一层——见评测真值点覆盖。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#文件命名", "href": "docs/products.html#文件命名", "title": "产物文档", "section": "文件命名", "text": "文件命名\n\nROI 目录名是 ROI_ 加补零到三位的编号（ROI_006）。注意 data/ 下的对齐控制点与 元数据表用的是不补零的写法（ROI_6），两者指同一个 ROI。\npatch_&lt;n&gt; 的 &lt;n&gt; 是该 ROI 内的顺序编号，从零起、不补零，原则上连续（例外见下表）。 同一个 ROI 里，同编号的光学、SAR、标签文件指同一块地面——这是配对的唯一依据， 文件里没有别的配对信息。\n编号不跨 ROI：每个 ROI 都有自己的 patch_0。\n\n扫描时逐一复核了上面这几条：\n\n\n\n检查\n结果\n\n\n\n\n光学与 SAR 编号不成对的 patch\n0 个\n\n\n编号不连续的 ROI\n1 个\n\n\n不符合命名规则的文件\n0 个\n\n\n\n具体是：\n\nTrain/ROI_027", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#数据类型与数值范围", "href": "docs/products.html#数据类型与数值范围", "title": "产物文档", "section": "数据类型与数值范围", "text": "数据类型与数值范围\n两种 patch 都是 512 × 512 像素的 GeoTIFF， 按条带存储、Deflate 压缩，头里带地理参考。\n\n\n\n\n\n\n\n\n\n光学 Optical/\nSAR SAR/\n\n\n\n\n文件数\n9,862\n9,862\n\n\n总大小\n1.2 GiB\n35.8 GiB\n\n\n数据类型\n8 位无符号整型（uint8）\n32 位浮点（float32）\n\n\n波段数\n1\n4\n\n\n尺寸（宽 × 高）\n512 × 512\n512 × 512\n\n\n像素间距\n7.5 m\n7.5 m\n\n\nnodata 值\n0.0\n0.0\n\n\n有效像素的数值范围\n波段 1：1 ~ 255\n波段 1：-0.01426 ~ 9.562波段 2：-0.02231 ~ 10.01波段 3：-3.13 ~ 3.021波段 4：-3.234 ~ 2.74\n\n\nnodata 像素占比\n0.00%\n0.00%\n\n\n含负值的 patch\n0\n9,862\n\n\nNaN 像素\n0\n0\n\n\n\n「有效像素」指不等于 nodata 值的像素；数值范围是在全部 patch 上逐像素取的极值，不是抽样。 nodata 像素占比按「所有波段都等于 nodata」计。\n几点容易踩的：\n\nSAR 含负值是正常的，不是坏数据。9,862 个 SAR patch 里有负值。归一化、取对数之前要先想清楚怎么处理它们。\n光学与 SAR 的像素间距相同，因为两者已被重采样到同一个网格上（见术语表「对齐影像」）。 注意它不是 CE-2 DOM 的原生分辨率——原始光学瓦片与这里的间距不同。\nSAR 各波段的物理含义属于数据来源，见来源文档。\n\n\n怎么读\n\n\n\n\n\n\n警告常见的 Python 影像库读这批 TIFF 会报解压错误\n\n\n\ntifffile（底层是 libdeflate）读它们会报 LIBDEFLATE_BAD_DATA。数据没坏——同一段条带字节 交给标准库 zlib 能完整解出、校验和也对得上，只是 libdeflate 更挑剔。 GDAL/rasterio 读取正常。\n\n\n不想装 GDAL 的话，用本仓库自带的读取器，它只依赖标准库和 numpy：\nfrom moondata.tiff import read_tiff\n\ninfo, optical = read_tiff(\"Processed_Data/Test/ROI_006/Optical/patch_0.tif\")\n_, sar = read_tiff(\"Processed_Data/Test/ROI_006/SAR/patch_0.tif\")\noptical.shape, optical.dtype   # (H, W, 1)  单波段也保留最后一维\nsar.shape, sar.dtype           # (H, W, C)，C 为上表的 SAR 波段数\ninfo.nodata, info.pixel_scale, info.origin", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#划分与数量", "href": "docs/products.html#划分与数量", "title": "产物文档", "section": "划分与数量", "text": "划分与数量\nROI_060 因与另一个 ROI 重复已从数据盘删除（原因见下）， 所以 ROI 与 patch 的数量有两种口径。凡引用数字，都要说明是哪一种。\n\n\n\n\nTrain\nVal\nTest\n合计\n\n\n\n\nROI（现存）\n54\n6\n7\n67\n\n\nROI（含已删除）\n54\n7\n7\n68\n\n\npatch 对（现存）\n7,907\n825\n1,130\n9,862\n\n\npatch 对（含已删除）\n7,907\n977\n1,130\n10,014\n\n\n\n「patch 对」指一张光学 patch 加一张 SAR patch。不指明口径时，本项目说的都是「现存」。\n\n\n\n\n\n\n注记已删除的 ROI_060（原属 Val）\n\n\n\n与 Test/ROI_037 为同一地点(PRODUCT_ID LSZ_01790_2CD_EKU_15S319_V1, CE2 tile H219_10S041W), 152 个光学 patch 中 152 个与 ROI_037 逐像素相同, 造成 Test/Val 不独立。删除于 2026-09-20；删除时它有 152 个 patch 对，其中 145 个带评测真值点。这两个数取自删除时留下的文件清单 data/metadata/removed_ROI_060_manifest.txt——清单只有文件名，所以它的评测真值点点数未知，含已删除口径下的点数一律记为「未知」。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#评测真值点覆盖", "href": "docs/products.html#评测真值点覆盖", "title": "产物文档", "section": "评测真值点覆盖", "text": "评测真值点覆盖\n评测真值点（术语表有专条）是人工在单个 patch 上标注的光学–SAR 同名点，用来评测配准精度。 它只存在于Val、Test，而且不是每个 patch 都有。\n\n\n\n划分\npatch 对\n有真值点的\n覆盖率\n真值点对数\n\n\n\n\nTrain\n7,907\n0\n0.0%\n0\n\n\nVal\n825\n652\n79.0%\n5,289\n\n\nVal（含已删除）\n977\n797\n81.6%\n未知\n\n\nTest\n1,130\n953\n84.3%\n7,742\n\n\n\n\n在Val、Test（现存口径）的 1,955 个 patch 对中， 1,605 个带评测真值点，覆盖率 82.1%。 剩下的 patch 评测时要跳过，不能当作「零误差」或「零个点」参与平均。\n每个带真值点的 patch 上有 7 ~ 11 对点， 中位数 8。\n训练集没有评测真值点：训练集不需要被评测。\n\n\n标签文件格式\nLabel/patch_&lt;n&gt;.txt 是空白分隔的纯文本，每行一对点， 4 列：光学 x、光学 y、SAR x、SAR y，单位是 patch 内像素。\n\n\n\n\n\n\n重要y 坐标取负\n\n\n\n标签文件里的 y 是负的像素行号，与 data/ 下的对齐控制点不同。 扫描复核结果：全部标签文件的 y 列均 ≤ 0，与约定一致。 读的时候取一次负、写的时候再取一次负，中间一律用正的行号。详见术语表「坐标符号约定」。\n\n\n同名的 patch_&lt;n&gt;.prj 是标注软件随标签一起写出的，读标签用不到它。 其中 1,584 个只有一个 GUID 占位、不含投影信息， 21 个写了完整的 WKT 投影， 0 个是别的内容。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#与窗口清单的数量差", "href": "docs/products.html#与窗口清单的数量差", "title": "产物文档", "section": "与窗口清单的数量差", "text": "与窗口清单的数量差\ndata/windows/ 下的窗口清单（windows.json、windows_train.json）逐 ROI 记录了每个 patch 的窗口。 按理它与产物应当一一对应，实际上对不上：\n\n\n\n划分\n清单中的窗口\n清单中的 unresolved\n产物中的 patch 对\n\n\n\n\nTrain\n7,886\n3\n7,907\n\n\nVal\n977\n0\n977\n\n\nTest\n1,130\n0\n1,130\n\n\n\n这里的产物数量按含已删除口径计（清单里仍有 ROI_060）。 清单合计 9,993 个窗口、另有 3 个 unresolved （清单自己承认没能对上的窗口），产物合计 10,014 个 patch 对。 差异全部集中在下面这些 ROI：\n\n\n\nROI\n划分\n清单中的窗口\nunresolved\n产物中的 patch 对\n差\n\n\n\n\nROI_027\nTrain\n234\n3\n234\n+0\n\n\nROI_073\nTrain\n98\n0\n119\n+21\n\n\n\n「产物 − 窗口」合计 +21；若把 unresolved 也算作清单记录过的窗口， 合计 +18——此前口头流传的那个差数是后一种算法。\n这两处差异的来历（据数据集作者说明）：\n\nROI_073：清单里的窗口本身是错的。 该 ROI 最初的对齐控制点有误（见 data/README.md 中 cropped_2 的重标记录），清单里的窗口是按那批错误的点算出来的，与现有产物对不上是 预期之内的。它在训练集，正向复现不要求与这里的旧窗口一致。\nROI_027：unresolved 是被丢弃的纯色废块。 作者印象中，当年有几个 patch 因光照原因基本全黑而被删掉，这与该 ROI 的编号断档（见文件命名）吻合。 旧迁移记录（MIGRATION.md，未入库）也写明该 ROI 缺的几个编号是「纯色废块」，与回忆一致。 详见该 ROI 的档案页。\n\n正向复现的验收只在验证集与测试集上设门：这两个划分的清单与产物完全对得上。 训练集上的差异不影响验收，也不得为凑数修改窗口清单或产物。", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/products.html#逐-roi-数量", "href": "docs/products.html#逐-roi-数量", "title": "产物文档", "section": "逐 ROI 数量", "text": "逐 ROI 数量\n点 ROI 编号进入它的档案页（条带参数、缩略图、已知问题），全部 ROI 的总览见 ROI 档案。\n\n\n\nROI\n划分\npatch 对\n有真值点的\n真值点对数\n\n\n\n\nROI_001\nTrain\n40\n0\n0\n\n\nROI_002\nTrain\n152\n0\n0\n\n\nROI_003\nTrain\n171\n0\n0\n\n\nROI_005\nTrain\n135\n0\n0\n\n\nROI_006\nTest\n81\n67\n538\n\n\nROI_007\nTest\n372\n286\n2,315\n\n\nROI_008\nTrain\n291\n0\n0\n\n\nROI_009\nTrain\n162\n0\n0\n\n\nROI_010\nTrain\n159\n0\n0\n\n\nROI_011\nTest\n92\n83\n706\n\n\nROI_012\nTrain\n105\n0\n0\n\n\nROI_013\nTrain\n54\n0\n0\n\n\nROI_015\nTrain\n98\n0\n0\n\n\nROI_016\nTrain\n265\n0\n0\n\n\nROI_017\nTrain\n213\n0\n0\n\n\nROI_018\nTrain\n117\n0\n0\n\n\nROI_020\nTest\n112\n91\n739\n\n\nROI_021\nTrain\n108\n0\n0\n\n\nROI_023\nTrain\n175\n0\n0\n\n\nROI_024\nTrain\n239\n0\n0\n\n\nROI_025\nTrain\n222\n0\n0\n\n\nROI_026\nTrain\n190\n0\n0\n\n\nROI_027\nTrain\n234\n0\n0\n\n\nROI_030\nTrain\n74\n0\n0\n\n\nROI_031\nTrain\n149\n0\n0\n\n\nROI_033\nTrain\n269\n0\n0\n\n\nROI_034\nTrain\n199\n0\n0\n\n\nROI_035\nVal\n214\n172\n1,383\n\n\nROI_037\nTest\n159\n141\n1,133\n\n\nROI_038\nTrain\n64\n0\n0\n\n\nROI_042\nTrain\n21\n0\n0\n\n\nROI_043\nTrain\n48\n0\n0\n\n\nROI_045\nTrain\n58\n0\n0\n\n\nROI_046\nTrain\n165\n0\n0\n\n\nROI_047\nTrain\n31\n0\n0\n\n\nROI_048\nTrain\n24\n0\n0\n\n\nROI_049\nVal\n113\n88\n706\n\n\nROI_050\nTrain\n160\n0\n0\n\n\nROI_051\nTrain\n196\n0\n0\n\n\nROI_052\nTrain\n170\n0\n0\n\n\nROI_053\nTrain\n93\n0\n0\n\n\nROI_054\nTest\n168\n145\n1,187\n\n\nROI_055\nTrain\n214\n0\n0\n\n\nROI_056\nTrain\n296\n0\n0\n\n\nROI_057\nTrain\n229\n0\n0\n\n\nROI_058\nTrain\n248\n0\n0\n\n\nROI_059\nTest\n146\n140\n1,124\n\n\nROI_061\nTrain\n97\n0\n0\n\n\nROI_062\nTrain\n136\n0\n0\n\n\nROI_063\nTrain\n103\n0\n0\n\n\nROI_064\nTrain\n111\n0\n0\n\n\nROI_065\nTrain\n172\n0\n0\n\n\nROI_066\nTrain\n130\n0\n0\n\n\nROI_067\nTrain\n120\n0\n0\n\n\nROI_068\nTrain\n107\n0\n0\n\n\nROI_069\nTrain\n198\n0\n0\n\n\nROI_070\nVal\n168\n113\n910\n\n\nROI_071\nVal\n40\n30\n241\n\n\nROI_072\nTrain\n60\n0\n0\n\n\nROI_073\nTrain\n119\n0\n0\n\n\nROI_074\nTrain\n141\n0\n0\n\n\nROI_075\nVal\n183\n174\n1,442\n\n\nROI_076\nTrain\n58\n0\n0\n\n\nROI_077\nTrain\n165\n0\n0\n\n\nROI_078\nTrain\n167\n0\n0\n\n\nROI_079\nTrain\n185\n0\n0\n\n\nROI_080\nVal\n107\n75\n607", "crumbs": ["首页", "主体文档", "产物文档"]}, {"objectID": "docs/rois/ROI_001.html", "href": "docs/rois/ROI_001.html", "title": "ROI_001", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n40\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_001/\n\n\n对齐控制点\ndata/tie-points/ROI_1/\n\n\n元数据表中的写法\nROI_1"}, {"objectID": "docs/rois/ROI_001.html#概况", "href": "docs/rois/ROI_001.html#概况", "title": "ROI_001", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n40\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_001/\n\n\n对齐控制点\ndata/tie-points/ROI_1/\n\n\n元数据表中的写法\nROI_1"}, {"objectID": "docs/rois/ROI_001.html#mini-rf-条带", "href": "docs/rois/ROI_001.html#mini-rf-条带", "title": "ROI_001", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02319_2CD_EKU_23S131_V1\n官方\n\n\n轨道号\n2319\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-28T05:47:26\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n49.75°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n271.10°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,287 × 55,819 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.6 m\n实测\n\n\n有效分辨率（方位向）\n18.4 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_001.html#缩略图", "href": "docs/rois/ROI_001.html#缩略图", "title": "ROI_001", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 58.63 ~ 118.4\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.66 ~ -6.38 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_1/cropped/ce2/opt.tif、raw/ROI_1/cropped/ce2/sar.tif（3,189 × 9,928 像素），每 17 × 17 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_001.html#本页数字从哪来", "href": "docs/rois/ROI_001.html#本页数字从哪来", "title": "ROI_001", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_003.html", "href": "docs/rois/ROI_003.html", "title": "ROI_003", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n171\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_003/\n\n\n对齐控制点\ndata/tie-points/ROI_3/\n\n\n元数据表中的写法\nROI_3"}, {"objectID": "docs/rois/ROI_003.html#概况", "href": "docs/rois/ROI_003.html#概况", "title": "ROI_003", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n171\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_003/\n\n\n对齐控制点\ndata/tie-points/ROI_3/\n\n\n元数据表中的写法\nROI_3"}, {"objectID": "docs/rois/ROI_003.html#mini-rf-条带", "href": "docs/rois/ROI_003.html#mini-rf-条带", "title": "ROI_003", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_05705_2CD_EKU_57N232_V1\n官方\n\n\n轨道号\n5705\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-09-20T02:41:48\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n49.28°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n94.15°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n18,202 × 99,134 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n16.2 m\n实测\n\n\n有效分辨率（方位向）\n19.1 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_003.html#已知问题", "href": "docs/rois/ROI_003.html#已知问题", "title": "ROI_003", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_003.html#缩略图", "href": "docs/rois/ROI_003.html#缩略图", "title": "ROI_003", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 3.27 ~ 136.6\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.81 ~ -6.933 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_3/cropped/ce2/opt.tif、raw/ROI_3/cropped/ce2/sar.tif（9,788 × 34,128 像素），每 57 × 57 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_003.html#本页数字从哪来", "href": "docs/rois/ROI_003.html#本页数字从哪来", "title": "ROI_003", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_006.html", "href": "docs/rois/ROI_006.html", "title": "ROI_006", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n81\n\n\n带评测真值点的 patch\n67 / 81（82.7%）\n\n\n评测真值点对数\n538\n\n\n产物目录\nProcessed_Data/Test/ROI_006/\n\n\n对齐控制点\ndata/tie-points/ROI_6/\n\n\n元数据表中的写法\nROI_6"}, {"objectID": "docs/rois/ROI_006.html#概况", "href": "docs/rois/ROI_006.html#概况", "title": "ROI_006", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n81\n\n\n带评测真值点的 patch\n67 / 81（82.7%）\n\n\n评测真值点对数\n538\n\n\n产物目录\nProcessed_Data/Test/ROI_006/\n\n\n对齐控制点\ndata/tie-points/ROI_6/\n\n\n元数据表中的写法\nROI_6"}, {"objectID": "docs/rois/ROI_006.html#mini-rf-条带", "href": "docs/rois/ROI_006.html#mini-rf-条带", "title": "ROI_006", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02833_2CD_EKU_16S144_V1\n官方\n\n\n轨道号\n2833\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-02-06T13:57:30\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n49.47°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n89.84°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,275 × 65,239 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.5 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_006.html#缩略图", "href": "docs/rois/ROI_006.html#缩略图", "title": "ROI_006", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 65.3 ~ 111.8\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.58 ~ -5.218 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_6/cropped/ce2/opt.tif、raw/ROI_6/cropped/ce2/sar.tif（3,622 × 12,748 像素），每 22 × 22 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_006.html#本页数字从哪来", "href": "docs/rois/ROI_006.html#本页数字从哪来", "title": "ROI_006", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_008.html", "href": "docs/rois/ROI_008.html", "title": "ROI_008", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n291\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_008/\n\n\n对齐控制点\ndata/tie-points/ROI_8/\n\n\n元数据表中的写法\nROI_8"}, {"objectID": "docs/rois/ROI_008.html#概况", "href": "docs/rois/ROI_008.html#概况", "title": "ROI_008", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n291\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_008/\n\n\n对齐控制点\ndata/tie-points/ROI_8/\n\n\n元数据表中的写法\nROI_8"}, {"objectID": "docs/rois/ROI_008.html#mini-rf-条带", "href": "docs/rois/ROI_008.html#mini-rf-条带", "title": "ROI_008", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_03124_2CD_EKU_07N202_V1\n官方\n\n\n轨道号\n3124\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-03-01T10:21:14\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n46.44°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n90.48°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,635 × 65,327 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.9 m\n实测\n\n\n有效分辨率（方位向）\n18.9 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_008.html#已知问题", "href": "docs/rois/ROI_008.html#已知问题", "title": "ROI_008", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告明显的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（在每对 patch 上找光学与 SAR 的可信匹配、量两者的相对偏移，每个 ROI 按编号等间隔抽 24 对）把这几个 ROI 归为「明显错位」：patch 对的重叠面积中位数 66%~79%。偏移几乎都在 x 方向（横跨条带），y 方向基本为 0；错位程度与该 ROI 对齐控制点的拟合残差对得上。\n这项检验只能当参考：它能证明一对 patch「是同一个地方」，证明不了「不是」。待本人复核。\n本 ROI： 可信匹配里有 33% 的 patch 对错开超过半个 patch；对齐控制点中位拟合残差 161 px。\n同一条还涉及：ROI_016、ROI_025、ROI_050、ROI_052。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_008.html#缩略图", "href": "docs/rois/ROI_008.html#缩略图", "title": "ROI_008", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 74.49 ~ 139.2\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.36 ~ -4.492 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_8/cropped/ce2/opt.tif、raw/ROI_8/cropped/ce2/sar.tif（3,895 × 68,290 像素），每 114 × 114 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_008.html#本页数字从哪来", "href": "docs/rois/ROI_008.html#本页数字从哪来", "title": "ROI_008", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_010.html", "href": "docs/rois/ROI_010.html", "title": "ROI_010", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n159\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_010/\n\n\n对齐控制点\ndata/tie-points/ROI_10/\n\n\n元数据表中的写法\nROI_10"}, {"objectID": "docs/rois/ROI_010.html#概况", "href": "docs/rois/ROI_010.html#概况", "title": "ROI_010", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n159\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_010/\n\n\n对齐控制点\ndata/tie-points/ROI_10/\n\n\n元数据表中的写法\nROI_10"}, {"objectID": "docs/rois/ROI_010.html#mini-rf-条带", "href": "docs/rois/ROI_010.html#mini-rf-条带", "title": "ROI_010", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_06182_2CD_EKU_09N093_V1\n官方\n\n\n轨道号\n6182\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-10-27T13:27:18\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.38°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n270.23°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,636 × 98,461 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_010.html#已知问题", "href": "docs/rois/ROI_010.html#已知问题", "title": "ROI_010", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_010.html#缩略图", "href": "docs/rois/ROI_010.html#缩略图", "title": "ROI_010", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 58.73 ~ 107.2\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.62 ~ -5.642 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_10/cropped/ce2/opt.tif、raw/ROI_10/cropped/ce2/sar.tif（4,021 × 33,036 像素），每 56 × 56 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_010.html#本页数字从哪来", "href": "docs/rois/ROI_010.html#本页数字从哪来", "title": "ROI_010", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_012.html", "href": "docs/rois/ROI_012.html", "title": "ROI_012", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n105\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_012/\n\n\n对齐控制点\ndata/tie-points/ROI_12/\n\n\n元数据表中的写法\nROI_12"}, {"objectID": "docs/rois/ROI_012.html#概况", "href": "docs/rois/ROI_012.html#概况", "title": "ROI_012", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n105\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_012/\n\n\n对齐控制点\ndata/tie-points/ROI_12/\n\n\n元数据表中的写法\nROI_12"}, {"objectID": "docs/rois/ROI_012.html#mini-rf-条带", "href": "docs/rois/ROI_012.html#mini-rf-条带", "title": "ROI_012", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02786_2CD_EKU_36S193_V1\n官方\n\n\n轨道号\n2786\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-02-02T21:29:54\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n54.71°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n88.55°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,493 × 13,722 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n18.1 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_012.html#缩略图", "href": "docs/rois/ROI_012.html#缩略图", "title": "ROI_012", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 30.32 ~ 72.49\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.44 ~ -4.633 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_12/cropped/ce2/opt.tif、raw/ROI_12/cropped/ce2/sar.tif（3,389 × 16,373 像素），每 28 × 28 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_012.html#本页数字从哪来", "href": "docs/rois/ROI_012.html#本页数字从哪来", "title": "ROI_012", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_015.html", "href": "docs/rois/ROI_015.html", "title": "ROI_015", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n98\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_015/\n\n\n对齐控制点\ndata/tie-points/ROI_15/\n\n\n元数据表中的写法\nROI_15"}, {"objectID": "docs/rois/ROI_015.html#概况", "href": "docs/rois/ROI_015.html#概况", "title": "ROI_015", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n98\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_015/\n\n\n对齐控制点\ndata/tie-points/ROI_15/\n\n\n元数据表中的写法\nROI_15"}, {"objectID": "docs/rois/ROI_015.html#mini-rf-条带", "href": "docs/rois/ROI_015.html#mini-rf-条带", "title": "ROI_015", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_06680_2CD_EKU_58N297_V1\n官方\n\n\n轨道号\n6680\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-12-05T16:17:34\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.05°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.73°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n8,401 × 99,601 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n16.2 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_015.html#已知问题", "href": "docs/rois/ROI_015.html#已知问题", "title": "ROI_015", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_015.html#缩略图", "href": "docs/rois/ROI_015.html#缩略图", "title": "ROI_015", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 31.45 ~ 121.1\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -18 ~ -5.44 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_15/cropped/ce2/opt.tif、raw/ROI_15/cropped/ce2/sar.tif（4,518 × 30,679 像素），每 52 × 52 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_015.html#本页数字从哪来", "href": "docs/rois/ROI_015.html#本页数字从哪来", "title": "ROI_015", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_017.html", "href": "docs/rois/ROI_017.html", "title": "ROI_017", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n213\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_017/\n\n\n对齐控制点\ndata/tie-points/ROI_17/\n\n\n元数据表中的写法\nROI_17"}, {"objectID": "docs/rois/ROI_017.html#概况", "href": "docs/rois/ROI_017.html#概况", "title": "ROI_017", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n213\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_017/\n\n\n对齐控制点\ndata/tie-points/ROI_17/\n\n\n元数据表中的写法\nROI_17"}, {"objectID": "docs/rois/ROI_017.html#mini-rf-条带", "href": "docs/rois/ROI_017.html#mini-rf-条带", "title": "ROI_017", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02399_2CD_EKU_07S233_V1\n官方\n\n\n轨道号\n2399\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-03T11:49:06\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n47.76°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n89.37°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,196 × 65,293 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.1 m\n实测\n\n\n有效分辨率（方位向）\n18.4 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_017.html#已知问题", "href": "docs/rois/ROI_017.html#已知问题", "title": "ROI_017", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告与 ROI_054 的范围部分重叠\n\n\n\n与测试集的 ROI_054 范围重叠 57%，但 patch 级只有 17 个 patch 有重叠、且都不超过 16%，当时判断可接受。\n出处：旧参考文档 DATA_REFERENCE.md §4"}, {"objectID": "docs/rois/ROI_017.html#缩略图", "href": "docs/rois/ROI_017.html#缩略图", "title": "ROI_017", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 79.24 ~ 120.7\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.61 ~ -4.714 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_17/cropped/ce2/opt.tif、raw/ROI_17/cropped/ce2/sar.tif（3,757 × 36,396 像素），每 61 × 61 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_017.html#本页数字从哪来", "href": "docs/rois/ROI_017.html#本页数字从哪来", "title": "ROI_017", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_020.html", "href": "docs/rois/ROI_020.html", "title": "ROI_020", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n112\n\n\n带评测真值点的 patch\n91 / 112（81.2%）\n\n\n评测真值点对数\n739\n\n\n产物目录\nProcessed_Data/Test/ROI_020/\n\n\n对齐控制点\ndata/tie-points/ROI_20/\n\n\n元数据表中的写法\nROI_20"}, {"objectID": "docs/rois/ROI_020.html#概况", "href": "docs/rois/ROI_020.html#概况", "title": "ROI_020", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n112\n\n\n带评测真值点的 patch\n91 / 112（81.2%）\n\n\n评测真值点对数\n739\n\n\n产物目录\nProcessed_Data/Test/ROI_020/\n\n\n对齐控制点\ndata/tie-points/ROI_20/\n\n\n元数据表中的写法\nROI_20"}, {"objectID": "docs/rois/ROI_020.html#mini-rf-条带", "href": "docs/rois/ROI_020.html#mini-rf-条带", "title": "ROI_020", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04399_2CD_EKU_50S318_V1\n官方\n\n\n轨道号\n4399\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-06-09T14:11:37\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n49.39°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n271.86°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n6,873 × 66,561 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n17.2 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_020.html#缩略图", "href": "docs/rois/ROI_020.html#缩略图", "title": "ROI_020", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 59 ~ 99.98\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.51 ~ -5.649 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_20/cropped/ce2/opt.tif、raw/ROI_20/cropped/ce2/sar.tif（5,341 × 31,991 像素），每 54 × 54 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_020.html#本页数字从哪来", "href": "docs/rois/ROI_020.html#本页数字从哪来", "title": "ROI_020", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_023.html", "href": "docs/rois/ROI_023.html", "title": "ROI_023", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n175\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_023/\n\n\n对齐控制点\ndata/tie-points/ROI_23/\n\n\n元数据表中的写法\nROI_23"}, {"objectID": "docs/rois/ROI_023.html#概况", "href": "docs/rois/ROI_023.html#概况", "title": "ROI_023", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n175\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_023/\n\n\n对齐控制点\ndata/tie-points/ROI_23/\n\n\n元数据表中的写法\nROI_23"}, {"objectID": "docs/rois/ROI_023.html#mini-rf-条带", "href": "docs/rois/ROI_023.html#mini-rf-条带", "title": "ROI_023", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04730_2CD_EKU_35N160_V1\n官方\n\n\n轨道号\n4730\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-07-05T12:59:36\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.70°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n91.37°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,679 × 65,317 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.0 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_023.html#已知问题", "href": "docs/rois/ROI_023.html#已知问题", "title": "ROI_023", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_023.html#缩略图", "href": "docs/rois/ROI_023.html#缩略图", "title": "ROI_023", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 67.56 ~ 114.2\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.14 ~ -5.481 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_23/cropped/ce2/opt.tif、raw/ROI_23/cropped/ce2/sar.tif（4,540 × 32,793 像素），每 55 × 55 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_023.html#本页数字从哪来", "href": "docs/rois/ROI_023.html#本页数字从哪来", "title": "ROI_023", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_025.html", "href": "docs/rois/ROI_025.html", "title": "ROI_025", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n222\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_025/\n\n\n对齐控制点\ndata/tie-points/ROI_25/\n\n\n元数据表中的写法\nROI_25"}, {"objectID": "docs/rois/ROI_025.html#概况", "href": "docs/rois/ROI_025.html#概况", "title": "ROI_025", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n222\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_025/\n\n\n对齐控制点\ndata/tie-points/ROI_25/\n\n\n元数据表中的写法\nROI_25"}, {"objectID": "docs/rois/ROI_025.html#mini-rf-条带", "href": "docs/rois/ROI_025.html#mini-rf-条带", "title": "ROI_025", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04784_2CD_EKU_66S104_V1\n官方\n\n\n轨道号\n4784\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-07-09T20:07:06\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n49.50°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n87.83°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n13,881 × 66,004 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n17.1 m\n实测\n\n\n有效分辨率（方位向）\n17.9 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_025.html#已知问题", "href": "docs/rois/ROI_025.html#已知问题", "title": "ROI_025", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告明显的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（在每对 patch 上找光学与 SAR 的可信匹配、量两者的相对偏移，每个 ROI 按编号等间隔抽 24 对）把这几个 ROI 归为「明显错位」：patch 对的重叠面积中位数 66%~79%。偏移几乎都在 x 方向（横跨条带），y 方向基本为 0；错位程度与该 ROI 对齐控制点的拟合残差对得上。\n这项检验只能当参考：它能证明一对 patch「是同一个地方」，证明不了「不是」。待本人复核。\n本 ROI： 对齐控制点中位拟合残差 92 px。\n同一条还涉及：ROI_008、ROI_016、ROI_050、ROI_052。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_025.html#缩略图", "href": "docs/rois/ROI_025.html#缩略图", "title": "ROI_025", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 24 ~ 138.8\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -16.11 ~ -6.057 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_25/cropped/ce2/opt.tif、raw/ROI_25/cropped/ce2/sar.tif（4,033 × 39,190 像素），每 66 × 66 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_025.html#本页数字从哪来", "href": "docs/rois/ROI_025.html#本页数字从哪来", "title": "ROI_025", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_027.html", "href": "docs/rois/ROI_027.html", "title": "ROI_027", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n234\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_027/\n\n\n对齐控制点\ndata/tie-points/ROI_27/\n\n\n元数据表中的写法\nROI_27"}, {"objectID": "docs/rois/ROI_027.html#概况", "href": "docs/rois/ROI_027.html#概况", "title": "ROI_027", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n234\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_027/\n\n\n对齐控制点\ndata/tie-points/ROI_27/\n\n\n元数据表中的写法\nROI_27"}, {"objectID": "docs/rois/ROI_027.html#mini-rf-条带", "href": "docs/rois/ROI_027.html#mini-rf-条带", "title": "ROI_027", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04477_2CD_EKU_63S237_V1\n官方\n\n\n轨道号\n4477\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-06-15T17:17:29\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n48.90°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n271.87°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n12,922 × 66,151 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n54.9 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_027.html#已知问题", "href": "docs/rois/ROI_027.html#已知问题", "title": "ROI_027", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）\n\n\n\n\n\n\n\n\n警告编号缺 95、98、99\n\n\n\n这三个 patch 是纯色废块（据作者回忆，是光照原因基本全黑），已丢弃，所以本 ROI 的编号不连续。窗口清单里与之对应的是 3 个 unresolved。读数据时请直接列目录，不要假设编号连续。\n出处：旧迁移记录 MIGRATION.md 末尾；2026-09-11 数据核查会话；作者回忆"}, {"objectID": "docs/rois/ROI_027.html#缩略图", "href": "docs/rois/ROI_027.html#缩略图", "title": "ROI_027", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 1 ~ 140.6\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -17.78 ~ -6.972 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_27/cropped/ce2/opt.tif、raw/ROI_27/cropped/ce2/sar.tif（6,949 × 39,190 像素），每 66 × 66 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_027.html#本页数字从哪来", "href": "docs/rois/ROI_027.html#本页数字从哪来", "title": "ROI_027", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_031.html", "href": "docs/rois/ROI_031.html", "title": "ROI_031", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n149\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_031/\n\n\n对齐控制点\ndata/tie-points/ROI_31/\n\n\n元数据表中的写法\nROI_31"}, {"objectID": "docs/rois/ROI_031.html#概况", "href": "docs/rois/ROI_031.html#概况", "title": "ROI_031", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n149\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_031/\n\n\n对齐控制点\ndata/tie-points/ROI_31/\n\n\n元数据表中的写法\nROI_31"}, {"objectID": "docs/rois/ROI_031.html#mini-rf-条带", "href": "docs/rois/ROI_031.html#mini-rf-条带", "title": "ROI_031", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02174_2CD_EKU_36N282_V1\n官方\n\n\n轨道号\n2174\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-16T18:53:05\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.87°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.88°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,935 × 50,089 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n17.7 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_031.html#缩略图", "href": "docs/rois/ROI_031.html#缩略图", "title": "ROI_031", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 36.97 ~ 78.97\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.69 ~ -6.839 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_31/cropped/ce2/opt.tif、raw/ROI_31/cropped/ce2/sar.tif（2,848 × 35,734 像素），每 60 × 60 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_031.html#本页数字从哪来", "href": "docs/rois/ROI_031.html#本页数字从哪来", "title": "ROI_031", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_034.html", "href": "docs/rois/ROI_034.html", "title": "ROI_034", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n199\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_034/\n\n\n对齐控制点\ndata/tie-points/ROI_34/\n\n\n元数据表中的写法\nROI_34"}, {"objectID": "docs/rois/ROI_034.html#概况", "href": "docs/rois/ROI_034.html#概况", "title": "ROI_034", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n199\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_034/\n\n\n对齐控制点\ndata/tie-points/ROI_34/\n\n\n元数据表中的写法\nROI_34"}, {"objectID": "docs/rois/ROI_034.html#mini-rf-条带", "href": "docs/rois/ROI_034.html#mini-rf-条带", "title": "ROI_034", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02457_2CD_EKU_49S174_V1\n官方\n\n\n轨道号\n2457\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-08T01:22:33\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.72°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n87.52°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n6,071 × 32,998 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n16.8 m\n实测\n\n\n有效分辨率（方位向）\n18.3 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_034.html#已知问题", "href": "docs/rois/ROI_034.html#已知问题", "title": "ROI_034", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告一幅 CE-2 分幅的经度差了 180°\n\n\n\n该分幅的名字写的是东经 175°，按坐标算出来是西经 5°。现有产物与旧版逐像素一致；只有将来从原始数据重新对齐时才会碰到。\n出处：2026-09-11 数据核查会话"}, {"objectID": "docs/rois/ROI_034.html#缩略图", "href": "docs/rois/ROI_034.html#缩略图", "title": "ROI_034", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 36.61 ~ 92.34\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -11.83 ~ -5.062 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_34/cropped/ce2/opt.tif、raw/ROI_34/cropped/ce2/sar.tif（7,191 × 17,599 像素），每 30 × 30 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_034.html#本页数字从哪来", "href": "docs/rois/ROI_034.html#本页数字从哪来", "title": "ROI_034", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_037.html", "href": "docs/rois/ROI_037.html", "title": "ROI_037", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n159\n\n\n带评测真值点的 patch\n141 / 159（88.7%）\n\n\n评测真值点对数\n1,133\n\n\n产物目录\nProcessed_Data/Test/ROI_037/\n\n\n对齐控制点\ndata/tie-points/ROI_37/\n\n\n元数据表中的写法\nROI_37"}, {"objectID": "docs/rois/ROI_037.html#概况", "href": "docs/rois/ROI_037.html#概况", "title": "ROI_037", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n159\n\n\n带评测真值点的 patch\n141 / 159（88.7%）\n\n\n评测真值点对数\n1,133\n\n\n产物目录\nProcessed_Data/Test/ROI_037/\n\n\n对齐控制点\ndata/tie-points/ROI_37/\n\n\n元数据表中的写法\nROI_37"}, {"objectID": "docs/rois/ROI_037.html#mini-rf-条带", "href": "docs/rois/ROI_037.html#mini-rf-条带", "title": "ROI_037", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01790_2CD_EKU_15S319_V1\n官方\n\n\n轨道号\n1790\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-11-16T16:34:15\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.04°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n270.15°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,632 × 66,155 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_037.html#已知问题", "href": "docs/rois/ROI_037.html#已知问题", "title": "ROI_037", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告与 ROI_060 重复（ROI_060 已删除）\n\n\n\nROI_060 与本 ROI 是同一块地（同一条 Mini-RF 条带、同一幅 CE-2 分幅，152 个光学 patch 逐像素相同），2026-09-20 删除了 ROI_060、保留本 ROI。两边当年都做过评测真值点标注。\n出处：删除清单；旧参考文档 DATA_REFERENCE.md §4"}, {"objectID": "docs/rois/ROI_037.html#缩略图", "href": "docs/rois/ROI_037.html#缩略图", "title": "ROI_037", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 36.53 ~ 71.28\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.37 ~ -7.265 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_37/cropped/ce2/opt.tif、raw/ROI_37/cropped/ce2/sar.tif（3,094 × 34,429 像素），每 58 × 58 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_037.html#本页数字从哪来", "href": "docs/rois/ROI_037.html#本页数字从哪来", "title": "ROI_037", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_042.html", "href": "docs/rois/ROI_042.html", "title": "ROI_042", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n21\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_042/\n\n\n对齐控制点\ndata/tie-points/ROI_42/\n\n\n元数据表中的写法\nROI_42"}, {"objectID": "docs/rois/ROI_042.html#概况", "href": "docs/rois/ROI_042.html#概况", "title": "ROI_042", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n21\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_042/\n\n\n对齐控制点\ndata/tie-points/ROI_42/\n\n\n元数据表中的写法\nROI_42"}, {"objectID": "docs/rois/ROI_042.html#mini-rf-条带", "href": "docs/rois/ROI_042.html#mini-rf-条带", "title": "ROI_042", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_05032_2CD_EKU_50N208_V1\n官方\n\n\n轨道号\n5032\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-07-29T06:17:26\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n48.20°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n91.55°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n6,395 × 66,220 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n50.5 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_042.html#缩略图", "href": "docs/rois/ROI_042.html#缩略图", "title": "ROI_042", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 46.91 ~ 149.8\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.77 ~ -6.333 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_42/cropped/ce2/opt.tif、raw/ROI_42/cropped/ce2/sar.tif（3,439 × 7,872 像素），每 14 × 14 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_042.html#本页数字从哪来", "href": "docs/rois/ROI_042.html#本页数字从哪来", "title": "ROI_042", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_045.html", "href": "docs/rois/ROI_045.html", "title": "ROI_045", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n58\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_045/\n\n\n对齐控制点\ndata/tie-points/ROI_45/\n\n\n元数据表中的写法\nROI_45"}, {"objectID": "docs/rois/ROI_045.html#概况", "href": "docs/rois/ROI_045.html#概况", "title": "ROI_045", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n58\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_045/\n\n\n对齐控制点\ndata/tie-points/ROI_45/\n\n\n元数据表中的写法\nROI_45"}, {"objectID": "docs/rois/ROI_045.html#mini-rf-条带", "href": "docs/rois/ROI_045.html#mini-rf-条带", "title": "ROI_045", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01395_2CD_EKU_13N009_V1\n官方\n\n\n轨道号\n1395\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-16T13:49:05\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n51.65°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.20°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,189 × 20,315 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n18.4 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_045.html#缩略图", "href": "docs/rois/ROI_045.html#缩略图", "title": "ROI_045", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 40.32 ~ 76.68\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.05 ~ -5.758 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_45/cropped/ce2/opt.tif、raw/ROI_45/cropped/ce2/sar.tif（2,574 × 19,145 像素），每 32 × 32 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_045.html#本页数字从哪来", "href": "docs/rois/ROI_045.html#本页数字从哪来", "title": "ROI_045", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_047.html", "href": "docs/rois/ROI_047.html", "title": "ROI_047", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n31\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_047/\n\n\n对齐控制点\ndata/tie-points/ROI_47/\n\n\n元数据表中的写法\nROI_47"}, {"objectID": "docs/rois/ROI_047.html#概况", "href": "docs/rois/ROI_047.html#概况", "title": "ROI_047", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n31\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_047/\n\n\n对齐控制点\ndata/tie-points/ROI_47/\n\n\n元数据表中的写法\nROI_47"}, {"objectID": "docs/rois/ROI_047.html#mini-rf-条带", "href": "docs/rois/ROI_047.html#mini-rf-条带", "title": "ROI_047", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02409_2CD_EKU_47S224_V1\n官方\n\n\n轨道号\n2409\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-04T06:55:03\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n54.92°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n86.87°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,728 × 7,329 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n16.7 m\n实测\n\n\n有效分辨率（方位向）\n18.9 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_047.html#缩略图", "href": "docs/rois/ROI_047.html#缩略图", "title": "ROI_047", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 37.94 ~ 94.93\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.41 ~ -6.274 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_47/cropped/ce2/opt.tif、raw/ROI_47/cropped/ce2/sar.tif（2,897 × 8,400 像素），每 14 × 14 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_047.html#本页数字从哪来", "href": "docs/rois/ROI_047.html#本页数字从哪来", "title": "ROI_047", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_049.html", "href": "docs/rois/ROI_049.html", "title": "ROI_049", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n113\n\n\n带评测真值点的 patch\n88 / 113（77.9%）\n\n\n评测真值点对数\n706\n\n\n产物目录\nProcessed_Data/Val/ROI_049/\n\n\n对齐控制点\ndata/tie-points/ROI_49/\n\n\n元数据表中的写法\nROI_49"}, {"objectID": "docs/rois/ROI_049.html#概况", "href": "docs/rois/ROI_049.html#概况", "title": "ROI_049", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n113\n\n\n带评测真值点的 patch\n88 / 113（77.9%）\n\n\n评测真值点对数\n706\n\n\n产物目录\nProcessed_Data/Val/ROI_049/\n\n\n对齐控制点\ndata/tie-points/ROI_49/\n\n\n元数据表中的写法\nROI_49"}, {"objectID": "docs/rois/ROI_049.html#mini-rf-条带", "href": "docs/rois/ROI_049.html#mini-rf-条带", "title": "ROI_049", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01777_2CD_EKU_17N334_V1\n官方\n\n\n轨道号\n1777\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-11-15T14:19:47\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.47°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.29°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,702 × 66,641 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.1 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_049.html#缩略图", "href": "docs/rois/ROI_049.html#缩略图", "title": "ROI_049", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 40.63 ~ 74.91\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -16.07 ~ -5.968 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_49/cropped/ce2/opt.tif、raw/ROI_49/cropped/ce2/sar.tif（4,094 × 33,394 像素），每 56 × 56 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_049.html#本页数字从哪来", "href": "docs/rois/ROI_049.html#本页数字从哪来", "title": "ROI_049", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_051.html", "href": "docs/rois/ROI_051.html", "title": "ROI_051", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n196\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_051/\n\n\n对齐控制点\ndata/tie-points/ROI_51/\n\n\n元数据表中的写法\nROI_51"}, {"objectID": "docs/rois/ROI_051.html#概况", "href": "docs/rois/ROI_051.html#概况", "title": "ROI_051", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n196\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_051/\n\n\n对齐控制点\ndata/tie-points/ROI_51/\n\n\n元数据表中的写法\nROI_51"}, {"objectID": "docs/rois/ROI_051.html#mini-rf-条带", "href": "docs/rois/ROI_051.html#mini-rf-条带", "title": "ROI_051", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01645_2CD_EKU_41N110_V1\n官方\n\n\n轨道号\n1645\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-11-05T05:24:54\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.12°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.21°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n5,427 × 65,731 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n16.7 m\n实测\n\n\n有效分辨率（方位向）\n18.9 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_051.html#缩略图", "href": "docs/rois/ROI_051.html#缩略图", "title": "ROI_051", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 69.83 ~ 153.9\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.43 ~ -4.964 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_51/cropped/ce2/opt.tif、raw/ROI_51/cropped/ce2/sar.tif（5,266 × 35,734 像素），每 60 × 60 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_051.html#本页数字从哪来", "href": "docs/rois/ROI_051.html#本页数字从哪来", "title": "ROI_051", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_053.html", "href": "docs/rois/ROI_053.html", "title": "ROI_053", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n93\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_053/\n\n\n对齐控制点\ndata/tie-points/ROI_53/\n\n\n元数据表中的写法\nROI_53"}, {"objectID": "docs/rois/ROI_053.html#概况", "href": "docs/rois/ROI_053.html#概况", "title": "ROI_053", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n93\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_053/\n\n\n对齐控制点\ndata/tie-points/ROI_53/\n\n\n元数据表中的写法\nROI_53"}, {"objectID": "docs/rois/ROI_053.html#mini-rf-条带", "href": "docs/rois/ROI_053.html#mini-rf-条带", "title": "ROI_053", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02199_2CD_EKU_01S255_V1\n官方\n\n\n轨道号\n2199\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-18T19:44:17\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n49.57°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n270.92°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,010 × 49,215 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.3 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_053.html#缩略图", "href": "docs/rois/ROI_053.html#缩略图", "title": "ROI_053", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 78.02 ~ 132\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.91 ~ -4.609 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_53/cropped/ce2/opt.tif、raw/ROI_53/cropped/ce2/sar.tif（2,562 × 33,915 像素），每 57 × 57 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_053.html#本页数字从哪来", "href": "docs/rois/ROI_053.html#本页数字从哪来", "title": "ROI_053", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_055.html", "href": "docs/rois/ROI_055.html", "title": "ROI_055", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n214\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_055/\n\n\n对齐控制点\ndata/tie-points/ROI_55/\n\n\n元数据表中的写法\nROI_55"}, {"objectID": "docs/rois/ROI_055.html#概况", "href": "docs/rois/ROI_055.html#概况", "title": "ROI_055", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n214\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_055/\n\n\n对齐控制点\ndata/tie-points/ROI_55/\n\n\n元数据表中的写法\nROI_55"}, {"objectID": "docs/rois/ROI_055.html#mini-rf-条带", "href": "docs/rois/ROI_055.html#mini-rf-条带", "title": "ROI_055", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_04755_2CD_EKU_35N135_V1\n官方\n\n\n轨道号\n4755\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-07-07T12:06:05\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n50.53°\n官方\n\n\n视向\nRIGHT\n官方\n\n\n视方位角\n91.83°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n5,130 × 65,465 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_055.html#已知问题", "href": "docs/rois/ROI_055.html#已知问题", "title": "ROI_055", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_056、ROI_065、ROI_068、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_055.html#缩略图", "href": "docs/rois/ROI_055.html#缩略图", "title": "ROI_055", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 64.82 ~ 135.1\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -12.74 ~ -5.387 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_55/cropped/ce2/opt.tif、raw/ROI_55/cropped/ce2/sar.tif（4,978 × 35,734 像素），每 60 × 60 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_055.html#本页数字从哪来", "href": "docs/rois/ROI_055.html#本页数字从哪来", "title": "ROI_055", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_057.html", "href": "docs/rois/ROI_057.html", "title": "ROI_057", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n229\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_057/\n\n\n对齐控制点\ndata/tie-points/ROI_57/\n\n\n元数据表中的写法\nROI_57"}, {"objectID": "docs/rois/ROI_057.html#概况", "href": "docs/rois/ROI_057.html#概况", "title": "ROI_057", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n229\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_057/\n\n\n对齐控制点\ndata/tie-points/ROI_57/\n\n\n元数据表中的写法\nROI_57"}, {"objectID": "docs/rois/ROI_057.html#mini-rf-条带", "href": "docs/rois/ROI_057.html#mini-rf-条带", "title": "ROI_057", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02121_2CD_EKU_28N338_V1\n官方\n\n\n轨道号\n2121\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-12T14:56:14\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.26°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.18°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,484 × 50,256 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n17.6 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_057.html#已知问题", "href": "docs/rois/ROI_057.html#已知问题", "title": "ROI_057", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告CE-2 分幅的投影参数被改错，读取时纠正\n\n\n\n本 ROI 所用的一幅 CE-2 分幅，随附投影文件的 lat_ts 抄成了相邻纬度带的值（E 带应为 35 却写成 21，I 带应为 −21 却写成 −35），像素和 geotransform 没动，整幅图因此被放到几度之外。旧代码在读取时按图幅名纠正，原文件不动；直接用通用 GIS 工具读原始瓦片会得到错误位置。\n本 ROI： 出问题的分幅：E218。\n同一条还涉及：ROI_058、ROI_065、ROI_070、ROI_073。\n出处：旧迁移记录 MIGRATION.md；旧参考文档 DATA_REFERENCE.md §2"}, {"objectID": "docs/rois/ROI_057.html#缩略图", "href": "docs/rois/ROI_057.html#缩略图", "title": "ROI_057", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 35.99 ~ 50.86\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.75 ~ -8.777 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_57/cropped/ce2/opt.tif、raw/ROI_57/cropped/ce2/sar.tif（4,127 × 59,529 像素），每 100 × 100 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_057.html#本页数字从哪来", "href": "docs/rois/ROI_057.html#本页数字从哪来", "title": "ROI_057", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_059.html", "href": "docs/rois/ROI_059.html", "title": "ROI_059", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n146\n\n\n带评测真值点的 patch\n140 / 146（95.9%）\n\n\n评测真值点对数\n1,124\n\n\n产物目录\nProcessed_Data/Test/ROI_059/\n\n\n对齐控制点\ndata/tie-points/ROI_59/\n\n\n元数据表中的写法\nROI_59"}, {"objectID": "docs/rois/ROI_059.html#概况", "href": "docs/rois/ROI_059.html#概况", "title": "ROI_059", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n测试集（Test）\n\n\npatch 对\n146\n\n\n带评测真值点的 patch\n140 / 146（95.9%）\n\n\n评测真值点对数\n1,124\n\n\n产物目录\nProcessed_Data/Test/ROI_059/\n\n\n对齐控制点\ndata/tie-points/ROI_59/\n\n\n元数据表中的写法\nROI_59"}, {"objectID": "docs/rois/ROI_059.html#mini-rf-条带", "href": "docs/rois/ROI_059.html#mini-rf-条带", "title": "ROI_059", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01740_2CD_EKU_20N011_V1\n官方\n\n\n轨道号\n1740\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-11-12T16:32:16\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.67°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.79°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,810 × 66,566 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.0 m\n实测\n\n\n有效分辨率（方位向）\n19.0 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_059.html#缩略图", "href": "docs/rois/ROI_059.html#缩略图", "title": "ROI_059", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 33.58 ~ 51.32\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.13 ~ -6.723 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_59/cropped/ce2/opt.tif、raw/ROI_59/cropped/ce2/sar.tif（4,213 × 35,001 像素），每 59 × 59 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_059.html#本页数字从哪来", "href": "docs/rois/ROI_059.html#本页数字从哪来", "title": "ROI_059", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_062.html", "href": "docs/rois/ROI_062.html", "title": "ROI_062", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n136\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_062/\n\n\n对齐控制点\ndata/tie-points/ROI_62/\n\n\n元数据表中的写法\nROI_62"}, {"objectID": "docs/rois/ROI_062.html#概况", "href": "docs/rois/ROI_062.html#概况", "title": "ROI_062", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n136\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_062/\n\n\n对齐控制点\ndata/tie-points/ROI_62/\n\n\n元数据表中的写法\nROI_62"}, {"objectID": "docs/rois/ROI_062.html#mini-rf-条带", "href": "docs/rois/ROI_062.html#mini-rf-条带", "title": "ROI_062", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_03029_2CD_EKU_32N301_V1\n官方\n\n\n轨道号\n3029\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-02-21T23:07:20\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.16°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n90.85°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n3,654 × 66,316 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n19.3 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_062.html#缩略图", "href": "docs/rois/ROI_062.html#缩略图", "title": "ROI_062", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 35.6 ~ 46.9\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.31 ~ -7.103 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_62/cropped/ce2/opt.tif、raw/ROI_62/cropped/ce2/sar.tif（3,545 × 32,793 像素），每 55 × 55 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_062.html#本页数字从哪来", "href": "docs/rois/ROI_062.html#本页数字从哪来", "title": "ROI_062", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_064.html", "href": "docs/rois/ROI_064.html", "title": "ROI_064", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n111\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_064/\n\n\n对齐控制点\ndata/tie-points/ROI_64/\n\n\n元数据表中的写法\nROI_64"}, {"objectID": "docs/rois/ROI_064.html#概况", "href": "docs/rois/ROI_064.html#概况", "title": "ROI_064", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n111\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_064/\n\n\n对齐控制点\ndata/tie-points/ROI_64/\n\n\n元数据表中的写法\nROI_64"}, {"objectID": "docs/rois/ROI_064.html#mini-rf-条带", "href": "docs/rois/ROI_064.html#mini-rf-条带", "title": "ROI_064", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_03307_2CD_EKU_34N014_V1\n官方\n\n\n轨道号\n3307\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-03-15T19:12:34\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.18°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n92.28°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n4,436 × 49,915 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n19.0 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_064.html#缩略图", "href": "docs/rois/ROI_064.html#缩略图", "title": "ROI_064", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 36.81 ~ 86.16\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.04 ~ -6.109 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_64/cropped/ce2/opt.tif、raw/ROI_64/cropped/ce2/sar.tif（4,304 × 25,681 像素），每 43 × 43 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_064.html#本页数字从哪来", "href": "docs/rois/ROI_064.html#本页数字从哪来", "title": "ROI_064", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_066.html", "href": "docs/rois/ROI_066.html", "title": "ROI_066", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n130\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_066/\n\n\n对齐控制点\ndata/tie-points/ROI_66/\n\n\n元数据表中的写法\nROI_66"}, {"objectID": "docs/rois/ROI_066.html#概况", "href": "docs/rois/ROI_066.html#概况", "title": "ROI_066", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n130\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_066/\n\n\n对齐控制点\ndata/tie-points/ROI_66/\n\n\n元数据表中的写法\nROI_66"}, {"objectID": "docs/rois/ROI_066.html#mini-rf-条带", "href": "docs/rois/ROI_066.html#mini-rf-条带", "title": "ROI_066", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01817_2CD_EKU_07N292_V1\n官方\n\n\n轨道号\n1817\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-11-18T17:44:07\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.28°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.87°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n1,897 × 66,473 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n18.2 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_066.html#缩略图", "href": "docs/rois/ROI_066.html#缩略图", "title": "ROI_066", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 62.5 ~ 95.8\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.23 ~ -5.794 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_66/cropped/ce2/opt.tif、raw/ROI_66/cropped/ce2/sar.tif（2,230 × 41,006 像素），每 69 × 69 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_066.html#本页数字从哪来", "href": "docs/rois/ROI_066.html#本页数字从哪来", "title": "ROI_066", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_068.html", "href": "docs/rois/ROI_068.html", "title": "ROI_068", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n107\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_068/\n\n\n对齐控制点\ndata/tie-points/ROI_68/\n\n\n元数据表中的写法\nROI_68"}, {"objectID": "docs/rois/ROI_068.html#概况", "href": "docs/rois/ROI_068.html#概况", "title": "ROI_068", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n107\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_068/\n\n\n对齐控制点\ndata/tie-points/ROI_68/\n\n\n元数据表中的写法\nROI_68"}, {"objectID": "docs/rois/ROI_068.html#mini-rf-条带", "href": "docs/rois/ROI_068.html#mini-rf-条带", "title": "ROI_068", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01425_2CD_EKU_10N339_V1\n官方\n\n\n轨道号\n1425\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-18T22:22:21\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.55°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n268.56°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,159 × 26,914 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.1 m\n实测\n\n\n有效分辨率（方位向）\n18.4 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_068.html#已知问题", "href": "docs/rois/ROI_068.html#已知问题", "title": "ROI_068", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_069、ROI_078、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_068.html#缩略图", "href": "docs/rois/ROI_068.html#缩略图", "title": "ROI_068", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 55.7 ~ 103.5\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.29 ~ -4.563 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_68/cropped/ce2/opt.tif、raw/ROI_68/cropped/ce2/sar.tif（2,538 × 31,776 像素），每 53 × 53 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_068.html#本页数字从哪来", "href": "docs/rois/ROI_068.html#本页数字从哪来", "title": "ROI_068", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_070.html", "href": "docs/rois/ROI_070.html", "title": "ROI_070", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n168\n\n\n带评测真值点的 patch\n113 / 168（67.3%）\n\n\n评测真值点对数\n910\n\n\n产物目录\nProcessed_Data/Val/ROI_070/\n\n\n对齐控制点\ndata/tie-points/ROI_70/\n\n\n元数据表中的写法\nROI_70"}, {"objectID": "docs/rois/ROI_070.html#概况", "href": "docs/rois/ROI_070.html#概况", "title": "ROI_070", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n168\n\n\n带评测真值点的 patch\n113 / 168（67.3%）\n\n\n评测真值点对数\n910\n\n\n产物目录\nProcessed_Data/Val/ROI_070/\n\n\n对齐控制点\ndata/tie-points/ROI_70/\n\n\n元数据表中的写法\nROI_70"}, {"objectID": "docs/rois/ROI_070.html#mini-rf-条带", "href": "docs/rois/ROI_070.html#mini-rf-条带", "title": "ROI_070", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01434_2CD_EKU_28S328_V1\n官方\n\n\n轨道号\n1434\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-19T17:01:43\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.72°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.73°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,666 × 30,045 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.3 m\n实测\n\n\n有效分辨率（方位向）\n18.7 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_070.html#已知问题", "href": "docs/rois/ROI_070.html#已知问题", "title": "ROI_070", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告CE-2 分幅的投影参数被改错，读取时纠正\n\n\n\n本 ROI 所用的一幅 CE-2 分幅，随附投影文件的 lat_ts 抄成了相邻纬度带的值（E 带应为 35 却写成 21，I 带应为 −21 却写成 −35），像素和 geotransform 没动，整幅图因此被放到几度之外。旧代码在读取时按图幅名纠正，原文件不动；直接用通用 GIS 工具读原始瓦片会得到错误位置。\n本 ROI： 出问题的分幅：I219。修正前被误判为「源影像缺失」，修正后本 ROI 的评测真值点全部可用。\n同一条还涉及：ROI_057、ROI_058、ROI_065、ROI_073。\n出处：旧迁移记录 MIGRATION.md；旧参考文档 DATA_REFERENCE.md §2"}, {"objectID": "docs/rois/ROI_070.html#缩略图", "href": "docs/rois/ROI_070.html#缩略图", "title": "ROI_070", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 41.39 ~ 125.4\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -13.29 ~ -2.824 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_70/cropped/ce2/opt.tif、raw/ROI_70/cropped/ce2/sar.tif（3,158 × 35,588 像素），每 60 × 60 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_070.html#本页数字从哪来", "href": "docs/rois/ROI_070.html#本页数字从哪来", "title": "ROI_070", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_072.html", "href": "docs/rois/ROI_072.html", "title": "ROI_072", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n60\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_072/\n\n\n对齐控制点\ndata/tie-points/ROI_72/\n\n\n元数据表中的写法\nROI_72"}, {"objectID": "docs/rois/ROI_072.html#概况", "href": "docs/rois/ROI_072.html#概况", "title": "ROI_072", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n60\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_072/\n\n\n对齐控制点\ndata/tie-points/ROI_72/\n\n\n元数据表中的写法\nROI_72"}, {"objectID": "docs/rois/ROI_072.html#mini-rf-条带", "href": "docs/rois/ROI_072.html#mini-rf-条带", "title": "ROI_072", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02645_2CD_EKU_28S338_V1\n官方\n\n\n轨道号\n2645\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-01-22T19:39:00\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.20°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n90.05°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,044 × 33,541 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.2 m\n实测\n\n\n有效分辨率（方位向）\n18.5 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_072.html#缩略图", "href": "docs/rois/ROI_072.html#缩略图", "title": "ROI_072", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 64.07 ~ 103\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.26 ~ -6.563 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_72/cropped/ce2/opt.tif、raw/ROI_72/cropped/ce2/sar.tif（1,983 × 18,820 像素），每 32 × 32 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_072.html#本页数字从哪来", "href": "docs/rois/ROI_072.html#本页数字从哪来", "title": "ROI_072", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_074.html", "href": "docs/rois/ROI_074.html", "title": "ROI_074", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n141\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_074/\n\n\n对齐控制点\ndata/tie-points/ROI_74/\n\n\n元数据表中的写法\nROI_74"}, {"objectID": "docs/rois/ROI_074.html#概况", "href": "docs/rois/ROI_074.html#概况", "title": "ROI_074", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n141\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_074/\n\n\n对齐控制点\ndata/tie-points/ROI_74/\n\n\n元数据表中的写法\nROI_74"}, {"objectID": "docs/rois/ROI_074.html#mini-rf-条带", "href": "docs/rois/ROI_074.html#mini-rf-条带", "title": "ROI_074", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01715_2CD_EKU_10N038_V1\n官方\n\n\n轨道号\n1715\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-11-10T17:19:25\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n52.10°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n269.66°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n2,787 × 66,435 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.3 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_074.html#已知问题", "href": "docs/rois/ROI_074.html#已知问题", "title": "ROI_074", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告ROI_73 的一份作废控制点实为本 ROI 的\n\n\n\ndata/tie-points/ROI_73/cropped/opt_tie_作废_实为ROI74.* 是当年标在本 ROI 影像上、却存进了ROI_73 文件夹的控制点。本 ROI 自己的控制点不受影响。\n出处：data/README.md"}, {"objectID": "docs/rois/ROI_074.html#缩略图", "href": "docs/rois/ROI_074.html#缩略图", "title": "ROI_074", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 32.9 ~ 43.06\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -14.67 ~ -6.873 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_74/cropped/ce2/opt.tif、raw/ROI_74/cropped/ce2/sar.tif（3,277 × 34,429 像素），每 58 × 58 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_074.html#本页数字从哪来", "href": "docs/rois/ROI_074.html#本页数字从哪来", "title": "ROI_074", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_076.html", "href": "docs/rois/ROI_076.html", "title": "ROI_076", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n58\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_076/\n\n\n对齐控制点\ndata/tie-points/ROI_76/\n\n\n元数据表中的写法\nROI_76"}, {"objectID": "docs/rois/ROI_076.html#概况", "href": "docs/rois/ROI_076.html#概况", "title": "ROI_076", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n58\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_076/\n\n\n对齐控制点\ndata/tie-points/ROI_76/\n\n\n元数据表中的写法\nROI_76"}, {"objectID": "docs/rois/ROI_076.html#mini-rf-条带", "href": "docs/rois/ROI_076.html#mini-rf-条带", "title": "ROI_076", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_01372_2CD_EKU_10S032_V1\n官方\n\n\n轨道号\n1372\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-10-14T20:13:34\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.25°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n270.38°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n1,748 × 13,748 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.4 m\n实测\n\n\n有效分辨率（方位向）\n18.8 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_076.html#缩略图", "href": "docs/rois/ROI_076.html#缩略图", "title": "ROI_076", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 49.94 ~ 82.72\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.79 ~ -6.569 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_76/cropped/ce2/opt.tif、raw/ROI_76/cropped/ce2/sar.tif（2,055 × 16,395 像素），每 28 × 28 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_076.html#本页数字从哪来", "href": "docs/rois/ROI_076.html#本页数字从哪来", "title": "ROI_076", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_078.html", "href": "docs/rois/ROI_078.html", "title": "ROI_078", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n167\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_078/\n\n\n对齐控制点\ndata/tie-points/ROI_78/\n\n\n元数据表中的写法\nROI_78"}, {"objectID": "docs/rois/ROI_078.html#概况", "href": "docs/rois/ROI_078.html#概况", "title": "ROI_078", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n训练集（Train）\n\n\npatch 对\n167\n\n\n带评测真值点的 patch\n无（训练集没有评测真值点）\n\n\n评测真值点对数\n—\n\n\n产物目录\nProcessed_Data/Train/ROI_078/\n\n\n对齐控制点\ndata/tie-points/ROI_78/\n\n\n元数据表中的写法\nROI_78"}, {"objectID": "docs/rois/ROI_078.html#mini-rf-条带", "href": "docs/rois/ROI_078.html#mini-rf-条带", "title": "ROI_078", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_03054_2CD_EKU_34S276_V1\n官方\n\n\n轨道号\n3054\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2010-02-23T22:35:27\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n48.46°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n88.35°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n5,317 × 66,048 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n18.1 m\n实测\n\n\n有效分辨率（方位向）\n18.5 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_078.html#已知问题", "href": "docs/rois/ROI_078.html#已知问题", "title": "ROI_078", "section": "已知问题", "text": "已知问题\n\n\n\n\n\n\n警告轻度的局部错位\n\n\n\n2026-09-11 的 patch 级配对检验（每个 ROI 抽 24 对）把这几个 ROI 归为「轻度错位」：patch 对的重叠面积中位数 77%~95%，偏移几十像素，错开超过半个 patch 的样本在 10% 以下。同一检验的对照组（ROI_5、ROI_12、ROI_21）重叠面积为 97%~99%。\n这项检验只能当参考（理由见「明显的局部错位」一条），待本人复核。\n同一条还涉及：ROI_002、ROI_003、ROI_010、ROI_015、ROI_023、ROI_026、ROI_027、ROI_048、ROI_054、ROI_055、ROI_056、ROI_065、ROI_068、ROI_069、ROI_079。\n出处：2026-09-11 数据核查会话（配对检验）"}, {"objectID": "docs/rois/ROI_078.html#缩略图", "href": "docs/rois/ROI_078.html#缩略图", "title": "ROI_078", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 69.24 ~ 116.5\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.48 ~ -6.014 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_78/cropped/ce2/opt.tif、raw/ROI_78/cropped/ce2/sar.tif（5,159 × 35,734 像素），每 60 × 60 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_078.html#本页数字从哪来", "href": "docs/rois/ROI_078.html#本页数字从哪来", "title": "ROI_078", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}, {"objectID": "docs/rois/ROI_080.html", "href": "docs/rois/ROI_080.html", "title": "ROI_080", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n107\n\n\n带评测真值点的 patch\n75 / 107（70.1%）\n\n\n评测真值点对数\n607\n\n\n产物目录\nProcessed_Data/Val/ROI_080/\n\n\n对齐控制点\ndata/tie-points/ROI_80/\n\n\n元数据表中的写法\nROI_80"}, {"objectID": "docs/rois/ROI_080.html#概况", "href": "docs/rois/ROI_080.html#概况", "title": "ROI_080", "section": "", "text": "项\n值\n\n\n\n\n所属划分\n验证集（Val）\n\n\npatch 对\n107\n\n\n带评测真值点的 patch\n75 / 107（70.1%）\n\n\n评测真值点对数\n607\n\n\n产物目录\nProcessed_Data/Val/ROI_080/\n\n\n对齐控制点\ndata/tie-points/ROI_80/\n\n\n元数据表中的写法\nROI_80"}, {"objectID": "docs/rois/ROI_080.html#mini-rf-条带", "href": "docs/rois/ROI_080.html#mini-rf-条带", "title": "ROI_080", "section": "Mini-RF 条带", "text": "Mini-RF 条带\n\n\n\n项\n值\n来源\n\n\n\n\n产品 ID\nLSZ_02094_2CD_EKU_50N003_V1\n官方\n\n\n轨道号\n2094\n官方\n\n\n任务阶段\nNOMINAL MISSION\n官方\n\n\n成像时刻（UTC）\n2009-12-10T12:08:35\n官方\n\n\n模式\nZOOM_S\n官方\n\n\n中心频率\n2.3800 GHz\n官方\n\n\n入射角\n53.71°\n官方\n\n\n视向\nLEFT\n官方\n\n\n视方位角\n267.31°\n官方\n\n\n投影\nEQUIRECTANGULAR\n官方\n\n\n地图分辨率\n4096.0 像素/度\n官方\n\n\n原生采样间隔\n7.4032 m\n官方\n\n\n条带尺寸（宽 × 长）\n8,836 × 66,501 像素\n官方\n\n\n波段数\n4\n官方\n\n\n有效分辨率（距离向）\n49.2 m\n实测\n\n\n有效分辨率（方位向）\n18.6 m\n实测\n\n\n\n「官方」取自该条带的 PDS 标签，「实测」是在本数据集影像上量出来的，口径见 data/README.md。"}, {"objectID": "docs/rois/ROI_080.html#缩略图", "href": "docs/rois/ROI_080.html#缩略图", "title": "ROI_080", "section": "缩略图", "text": "缩略图\n\n\n\n\n\n\n光学：灰度值，拉伸区间 55.21 ~ 112.4\n\n\n\n\n\n\n\nSAR：H + V 总功率（dB），拉伸区间 -15.16 ~ -5.622 dB\n\n\n\n\n\n取自对齐影像 raw/ROI_80/cropped/ce2/opt.tif、raw/ROI_80/cropped/ce2/sar.tif（6,867 × 31,890 像素），每 54 × 54 个像素取有效像素的均值并成一个，按行列原样画出；拉伸区间是有效像素的 2% 与 98% 分位。黑色是没有数据的区域，对齐影像按两者的外包框取景，所以 SAR 条带两侧常有大片黑边。"}, {"objectID": "docs/rois/ROI_080.html#本页数字从哪来", "href": "docs/rois/ROI_080.html#本页数字从哪来", "title": "ROI_080", "section": "本页数字从哪来", "text": "本页数字从哪来\n\npatch 数与评测真值点：统计快照 stats/snapshot.json，生成于 2026-09-23T07:25:37+08:00，数据指纹 sha256:521b8fec4c1e1984cf4094fd7f709c51642a15b45b03bca34f569a39f5a038fb。\n条带参数：元数据表 data/metadata/minirf_metadata.csv。\n缩略图：moondata thumbnails 生成于 2026-09-23T08:03:16+08:00。\n已知问题：docs/rois/known-issues.toml（手写，每条注明出处）。"}];
function __moondataOfflineSearchResponse() {
  return {
    status: 200,
    json: function () {
      return Promise.resolve(__moondataSearchDocuments);
    },
  };
}
/* <<< moondata:offline-search-index */
